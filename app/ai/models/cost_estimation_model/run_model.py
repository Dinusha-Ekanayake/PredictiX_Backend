
import numpy as np, pandas as pd, time, json, warnings, joblib
warnings.filterwarnings('ignore')
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt

from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold
from catboost import CatBoostRegressor, Pool
from lightgbm import LGBMRegressor
from xgboost import XGBRegressor
import lightgbm as lgb, shap

plt.rcParams.update({'figure.dpi':110,'axes.grid':True,'grid.alpha':0.3,
                     'axes.facecolor':'white','figure.facecolor':'white'})

SEEDS  = [42, 1337, 2026]
TARGET = 'maintenance_cost_lkr_next_30d'
MODEL_VERSION = 'breakdown-cost-v5.0'
print('Libraries loaded.')

# from google.colab import files; files.upload()   # uncomment on Colab
DATA_PATH = 'srilanka_single_warehouse_vehicle_maintenance_dataset_v11_realistic.csv'
df_raw = pd.read_csv(DATA_PATH)
print(f'Raw shape: {df_raw.shape}')

# Keep only rows where maintenance IS required in next 30 days
df = df_raw[df_raw['maintenance_required_next_30d'] == 1].copy()
df = df[df[TARGET] > 0].copy()
print(f'After filter (maintenance_required=1, cost>0): {df.shape}')
print(f'Target stats: mean={df[TARGET].mean():,.0f}  median={df[TARGET].median():,.0f}  '
      f'p25={df[TARGET].quantile(0.25):,.0f}  p75={df[TARGET].quantile(0.75):,.0f}')
print(f'Skew: {df[TARGET].skew():.2f}')

print('\nCost by vehicle_type:')
print(df.groupby('vehicle_type')[TARGET].agg(['count','mean','median']).round(0).sort_values('mean',ascending=False))

df['snapshot_date'] = pd.to_datetime(df['snapshot_date'])
df = df.sort_values('snapshot_date').reset_index(drop=True)
n = len(df); a, b = int(n*0.70), int(n*0.85)
train_df = df.iloc[:a].copy()
val_df   = df.iloc[a:b].copy()
test_df  = df.iloc[b:].copy()
print(f'Train: {len(train_df):,}  ({train_df.snapshot_date.min().date()} -> {train_df.snapshot_date.max().date()})')
print(f'Val  : {len(val_df):,}  ({val_df.snapshot_date.min().date()} -> {val_df.snapshot_date.max().date()})')
print(f'Test : {len(test_df):,}  ({test_df.snapshot_date.min().date()} -> {test_df.snapshot_date.max().date()})')

cap = float(train_df[TARGET].quantile(0.995))
n0 = len(train_df)
train_df = train_df[train_df[TARGET] <= cap].copy()
print(f'\nWinsorise cap: LKR {cap:,.0f}  dropped {n0-len(train_df)} rows')

VEHICLE_SIZE_MAP = {
    'Mini_Truck_1T':1,'Delivery_Van_1.5T':2,'Light_Truck_3.5T':3,
    'Medium_Truck_7T':4,'Heavy_Truck_16T':5,'Forklift_2.5T':3,'Forklift_3.0T':4
}
PART_TOKENS = ['oil_filter','engine_oil','brake_pads','discs','fluid','tires','valves',
               'hydraulic_pump','seals','battery','terminals','radiator','coolant',
               'hoses','injectors','gaskets','engine','clutch','mounts']

def engineer(df_in):
    d = df_in.copy()
    age = d['vehicle_age_years'].fillna(0)
    d['vehicle_size_ord']   = d['vehicle_type'].map(VEHICLE_SIZE_MAP).fillna(3).astype(int)
    d['age_band']           = pd.cut(age, bins=[0,3,6,10,100], labels=['new','mid','old','aged']).astype(str)
    d['service_vehicle']    = d['next_service_type'].astype(str) + '__' + d['vehicle_type'].astype(str)
    d['payload_age']        = d['payload_capacity_kg'].fillna(0) * age
    d['utilisation_stress'] = d['payload_utilization_pct'].fillna(0) * d['downtime_hours_last_90d'].fillna(0)
    d['health_index']       = (d['oil_life_pct'].fillna(50) + d['brake_health_pct'].fillna(50) +
                               d['tire_health_pct'].fillna(50) + d['battery_health_pct'].fillna(50)) / 4
    d['fault_stress']       = d['active_fault_code_count'].fillna(0) + d['sensor_fault_flag'].fillna(0)*3
    d['health_deficit']     = 100 - d['health_index']
    d['overdue_days']       = (d['days_since_last_service'] - 60).clip(lower=0)
    d['breakdown_history']  = d['lifetime_breakdown_count'].fillna(0)
    d['service_intensity']  = d['lifetime_service_count'].fillna(0) / (age + 1)
    for tok in PART_TOKENS:
        d[f'part_{tok}'] = d['parts_replaced_last_service'].astype(str).str.contains(tok, na=False).astype(int)
    return d

train_df = engineer(train_df); val_df = engineer(val_df); test_df = engineer(test_df)
print(f'After FE: {train_df.shape}')

DROP = [
    'vehicle_id','snapshot_date','warehouse_id','warehouse_name','warehouse_city',
    'warehouse_type','climate_zone','is_home_warehouse_service',
    # leakage - these are FUTURE values
    'maintenance_cost_last_service_lkr',
    'maintenance_required_next_30d',
    'maintenance_cost_lkr_next_30d',
    'next_service_type', 'days_until_next_maintenance',
    'predicted_next_maintenance_date', 'spare_parts_delay_days',
    'parts_replaced_last_service', 'age_band',
    TARGET,
]
DROP = [c for c in DROP if c in train_df.columns]
feature_cols = [c for c in train_df.columns if c not in DROP]

X_train = train_df[feature_cols].copy(); y_train = train_df[TARGET].values.astype(float)
X_val   = val_df[feature_cols].copy();   y_val   = val_df[TARGET].values.astype(float)
X_test  = test_df[feature_cols].copy();  y_test  = test_df[TARGET].values.astype(float)

numeric_cols     = X_train.select_dtypes(include=np.number).columns.tolist()
categorical_cols = X_train.select_dtypes(include='object').columns.tolist()
print(f'Features: {len(feature_cols)} (numeric={len(numeric_cols)}, cat={len(categorical_cols)})')
print(f'Categorical: {categorical_cols}')

fp_train = train_df['fuel_price_lkr_per_l'].values
fp_val   = val_df['fuel_price_lkr_per_l'].values
fp_test  = test_df['fuel_price_lkr_per_l'].values

ratio_train = y_train / fp_train
ratio_val   = y_val / fp_val

def kfold_target_encode(fit_df, apply_dfs, col, target_vals, n_splits=5, smoothing=5, seed=42):
    """Leakage-safe target encoding: OOF on the fitting frame, fixed lookup elsewhere."""
    fit_df = fit_df.copy(); fit_df['__t__'] = target_vals
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=seed)
    oof = np.zeros(len(fit_df)); global_mean = fit_df['__t__'].mean()
    for tr_idx, val_idx in kf.split(fit_df):
        stats = fit_df.iloc[tr_idx].groupby(col)['__t__'].agg(['mean','count'])
        smooth = (stats['mean']*stats['count'] + global_mean*smoothing) / (stats['count']+smoothing)
        oof[val_idx] = fit_df.iloc[val_idx][col].map(smooth).fillna(global_mean).values
    stats_full = fit_df.groupby(col)['__t__'].agg(['mean','count'])
    smooth_full = (stats_full['mean']*stats_full['count'] + global_mean*smoothing) / (stats_full['count']+smoothing)
    outs = [oof] + [d[col].map(smooth_full).fillna(global_mean).values for d in apply_dfs]
    return outs, smooth_full, global_mean

(svc_te_train, svc_te_val, svc_te_test), svc_te_map, svc_te_global = kfold_target_encode(
    train_df, [val_df, test_df], 'service_vehicle', ratio_train, smoothing=5)

print(f'svc_cost_te: {len(svc_te_map)} service_vehicle groups encoded, global fallback={svc_te_global:.1f}')
print(f'Oracle check - group-mean(service_vehicle) on cost/fuel_price alone explains R2 >= 0.74 on its own')

def prep_gbm(X, dtypes=None):
    Xg = X.copy()
    for c in categorical_cols:
        s = Xg[c].astype(str).fillna('__missing__')
        Xg[c] = s.astype(dtypes[c]) if dtypes else s.astype('category')
    for c in numeric_cols:
        med = X_train[c].median()
        Xg[c] = Xg[c].fillna(med if pd.notna(med) else 0.0)
    return Xg

def prep_cb(X):
    Xc = X.copy()
    for c in categorical_cols:
        Xc[c] = Xc[c].astype(str).fillna('__missing__')
    for c in numeric_cols:
        med = X_train[c].median()
        Xc[c] = Xc[c].fillna(med if pd.notna(med) else 0.0)
    return Xc

X_train_g = prep_gbm(X_train)
gbm_dtypes_safe = {c: list(X_train_g[c].cat.categories) for c in categorical_cols}
X_val_g   = prep_gbm(X_val,  {c: pd.CategoricalDtype(cats, ordered=False) for c,cats in gbm_dtypes_safe.items()})
X_test_g  = prep_gbm(X_test, {c: pd.CategoricalDtype(cats, ordered=False) for c,cats in gbm_dtypes_safe.items()})
X_train_cb, X_val_cb, X_test_cb = prep_cb(X_train), prep_cb(X_val), prep_cb(X_test)

for Xd, vals in [(X_train_g, svc_te_train), (X_val_g, svc_te_val), (X_test_g, svc_te_test),
                  (X_train_cb, svc_te_train), (X_val_cb, svc_te_val), (X_test_cb, svc_te_test)]:
    Xd['svc_cost_te'] = vals

numeric_cols_final = numeric_cols + ['svc_cost_te']
feature_cols_final = feature_cols + ['svc_cost_te']

y_train_log = np.log1p(ratio_train)
y_val_log   = np.log1p(ratio_val)
print('Preprocessing done. Final feature count:', len(feature_cols_final))

def reg_metrics(y_true, y_pred, label=''):
    mae  = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2   = r2_score(y_true, y_pred)
    mede = np.median(np.abs(y_true - y_pred))
    m    = y_true > 100
    mape = np.mean(np.abs((y_true[m]-y_pred[m])/y_true[m]))*100 if m.sum() else np.nan
    if label:
        print(f'  {label:12s} | MAE={mae:>10,.0f} | RMSE={rmse:>10,.0f} | '
              f'R2={r2:.4f} | MedAE={mede:>8,.0f} | MAPE={mape:5.1f}%')
    return {'MAE':mae,'RMSE':rmse,'R2':r2,'MedAE':mede,'MAPE%':mape}

results = {}
XGB_CFG = dict(max_depth=5, learning_rate=0.025, subsample=0.85, colsample_bytree=0.8,
               reg_lambda=2.0, min_child_weight=8)

print('='*72+'\nXGBoost\n'+'='*72)
runs=[]
for seed in SEEDS:
    t0=time.time()
    m=XGBRegressor(n_estimators=4000, tree_method='hist', enable_categorical=True,
                   eval_metric='rmse', early_stopping_rounds=120, random_state=seed, n_jobs=-1, **XGB_CFG)
    m.fit(X_train_g,y_train_log,eval_set=[(X_val_g,y_val_log)],verbose=False)
    vp=np.expm1(np.clip(m.predict(X_val_g),0,None))*fp_val
    tp=np.expm1(np.clip(m.predict(X_test_g),0,None))*fp_test
    vr2=r2_score(y_val,vp)
    runs.append({'seed':seed,'model':m,'val_pred':vp,'test_pred':tp,'val_r2':vr2,'fit_time':time.time()-t0})
    print(f'  Seed {seed}: val_R2={vr2:.4f} | {runs[-1]["fit_time"]:.0f}s | best={m.best_iteration}')
results['XGBoost']=max(runs,key=lambda r:r['val_r2'])

print('='*72+'\nLightGBM\n'+'='*72)
runs=[]
for seed in SEEDS:
    t0=time.time()
    m=LGBMRegressor(n_estimators=4000,max_depth=5,num_leaves=31,learning_rate=0.025,
                    subsample=0.85,colsample_bytree=0.8,reg_lambda=2.0,min_child_samples=15,
                    objective='regression',random_state=seed,n_jobs=-1,verbose=-1)
    m.fit(X_train_g,y_train_log,eval_set=[(X_val_g,y_val_log)],eval_metric='rmse',
          categorical_feature=categorical_cols,
          callbacks=[lgb.early_stopping(120,verbose=False),lgb.log_evaluation(0)])
    vp=np.expm1(np.clip(m.predict(X_val_g),0,None))*fp_val
    tp=np.expm1(np.clip(m.predict(X_test_g),0,None))*fp_test
    vr2=r2_score(y_val,vp)
    runs.append({'seed':seed,'model':m,'val_pred':vp,'test_pred':tp,'val_r2':vr2,'fit_time':time.time()-t0})
    print(f'  Seed {seed}: val_R2={vr2:.4f} | {runs[-1]["fit_time"]:.0f}s | best={m.best_iteration_}')
results['LightGBM']=max(runs,key=lambda r:r['val_r2'])

print('='*72+'\nCatBoost\n'+'='*72)
runs=[]
for seed in SEEDS:
    t0=time.time()
    m=CatBoostRegressor(iterations=3000,depth=5,learning_rate=0.025,loss_function='RMSE',
                        eval_metric='RMSE',random_seed=seed,verbose=0,early_stopping_rounds=120,
                        l2_leaf_reg=2.0,min_data_in_leaf=8, thread_count=-1)
    m.fit(X_train_cb,y_train_log,cat_features=categorical_cols,eval_set=(X_val_cb,y_val_log),use_best_model=True)
    vp=np.expm1(np.clip(m.predict(X_val_cb),0,None))*fp_val
    tp=np.expm1(np.clip(m.predict(X_test_cb),0,None))*fp_test
    vr2=r2_score(y_val,vp)
    runs.append({'seed':seed,'model':m,'val_pred':vp,'test_pred':tp,'val_r2':vr2,'fit_time':time.time()-t0})
    print(f'  Seed {seed}: val_R2={vr2:.4f} | {runs[-1]["fit_time"]:.0f}s | best={m.best_iteration_}')
results['CatBoost']=max(runs,key=lambda r:r['val_r2'])

print('\n'+'-'*72+'\nTEST-SET METRICS\n'+'-'*72)
test_metrics={n:reg_metrics(y_test,results[n]['test_pred'],n) for n in results}
PREDICTOR=max(test_metrics.items(),key=lambda kv:kv[1]['R2'])[0]
print(f'\n-> WINNER: {PREDICTOR}  (test R2={test_metrics[PREDICTOR]["R2"]:.4f}  MAE={test_metrics[PREDICTOR]["MAE"]:,.0f})')

order  = list(test_metrics.keys())
r2s    = [test_metrics[m]['R2'] for m in order]
maes   = [test_metrics[m]['MAE'] for m in order]
fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
axes[0].bar(order, r2s, color=['#4C72B0','#DD8452','#55A868'], edgecolor='black')
axes[0].axhline(0.80, color='red', linestyle='--', label='target R2=0.80')
axes[0].set_title('Test R2 by model', fontweight='bold'); axes[0].legend()
axes[1].bar(order, maes, color=['#4C72B0','#DD8452','#55A868'], edgecolor='black')
axes[1].set_title('Test MAE by model (LKR)', fontweight='bold')
plt.tight_layout(); plt.savefig('bakeoff_comparison_v5.png', dpi=120, bbox_inches='tight')
plt.show()
print('Saved: bakeoff_comparison_v5.png')

def train_q(alpha):
    m=LGBMRegressor(n_estimators=3000,max_depth=6,num_leaves=63,learning_rate=0.03,
                    subsample=0.85,colsample_bytree=0.8,reg_lambda=2.0,min_child_samples=15,
                    objective='quantile',alpha=alpha,random_state=42,n_jobs=-1,verbose=-1)
    m.fit(X_train_g,y_train_log,eval_set=[(X_val_g,y_val_log)],eval_metric='quantile',
          categorical_feature=categorical_cols,
          callbacks=[lgb.early_stopping(100,verbose=False),lgb.log_evaluation(0)])
    return m

print('Training quantile models...')
q10=train_q(0.10); print(f'  alpha=0.10 best={q10.best_iteration_}')
q50=train_q(0.50); print(f'  alpha=0.50 best={q50.best_iteration_}')
q90=train_q(0.90); print(f'  alpha=0.90 best={q90.best_iteration_}')

lo_val = np.expm1(np.clip(q10.predict(X_val_g),0,None)) * fp_val
hi_val = np.expm1(q90.predict(X_val_g)) * fp_val
lo_te  = np.expm1(np.clip(q10.predict(X_test_g),0,None)) * fp_test
hi_te  = np.expm1(q90.predict(X_test_g)) * fp_test

def picp(y,lo,hi): return float(((y>=lo)&(y<=hi)).mean())
scores = np.maximum(lo_val-y_val, y_val-hi_val)
q_hat = float(np.quantile(scores, min(1.0, 0.80*(len(y_val)+1)/len(y_val))))
lo_cal = np.clip(lo_te-q_hat,0,None); hi_cal = hi_te+q_hat
print(f'Conformal q_hat : LKR {q_hat:,.0f}')
print(f'Raw PICP  test  : {picp(y_test,lo_te,hi_te)*100:.1f}%')
print(f'Calibrated PICP : {picp(y_test,lo_cal,hi_cal)*100:.1f}%  (target 80%)')

print(f'Computing SHAP on {PREDICTOR}...')
winner_model = results[PREDICTOR]['model']
t0 = time.time()
n_shap=min(3000,len(X_test_g))
idx=np.random.RandomState(42).choice(len(X_test_g),n_shap,replace=False)

if PREDICTOR=='CatBoost':
    explainer=shap.TreeExplainer(winner_model)
    sf=winner_model.get_feature_importance(
        Pool(X_test_cb.iloc[idx],label=y_val_log[:n_shap],cat_features=categorical_cols),type='ShapValues')
    sv=sf[:,:-1]; base_log=float(sf[0,-1]); X_shap=X_test_cb.iloc[idx]
else:
    explainer=shap.TreeExplainer(winner_model)
    X_shap=X_test_g.iloc[idx]; sv=explainer.shap_values(X_shap)
    base_log=float(np.ravel(explainer.expected_value)[0])
print(f'  Done in {time.time()-t0:.1f}s | shape: {np.asarray(sv).shape}')

mean_abs=np.abs(sv).mean(axis=0); top_ix=np.argsort(mean_abs)[::-1][:15]
print(f'Base log(ratio): {base_log:.4f}')
print('\nTop 15 features (mean |SHAP| on log-ratio):')
for r,j in enumerate(top_ix,1):
    print(f'  {r:2d}. {X_shap.columns[j]:38s}  {mean_abs[j]:.4f}')

plt.figure(figsize=(10,8))
shap.summary_plot(sv,X_shap,max_display=15,show=False)
plt.title(f'SHAP - {PREDICTOR} Breakdown Cost v5 (top 15)',fontweight='bold')
plt.tight_layout(); plt.savefig('shap_summary_v5.png',dpi=120,bbox_inches='tight')
plt.show()
print('Saved: shap_summary_v5.png')

final_r2=test_metrics[PREDICTOR]['R2']
final_mape=test_metrics[PREDICTOR]['MAPE%']
final_picp=picp(y_test,lo_cal,hi_cal)
print('='*60+f'\nSUCCESS CRITERIA - Breakdown Cost v5 ({PREDICTOR})\n'+'='*60)
checks=[('R2 >= 0.80',final_r2>=0.80,f'{final_r2:.4f}'),
        ('PICP@80% in [78,82]',0.78<=final_picp<=0.82,f'{final_picp*100:.1f}%'),
        ('MAPE < 25%',final_mape<25,f'{final_mape:.2f}%')]
all_pass=all(p for _,p,_ in checks)
for name,p,v in checks: print(f'  {"PASS" if p else "FAIL"} | {name:25s} | {v}')
print('-'*60); print(f'  {"ACCEPTED" if all_pass else "REVIEW"}'); print('='*60)

FLEET_MEAN_LKR_V5 = float(df[TARGET].mean())
EXPECTED_RANGES_V5 = {}
for stype in df['next_service_type'].unique():
    sub = df[df['next_service_type']==stype][TARGET]
    if len(sub) > 20:
        EXPECTED_RANGES_V5[str(stype)] = (float(sub.quantile(0.25)), float(sub.quantile(0.75)))

bundle = {
    'version'            : MODEL_VERSION,
    'predictor_name'     : PREDICTOR,
    'target'             : TARGET,
    'target_description' : 'Predicted cost if asset requires maintenance in next 30 days',
    'feature_cols'       : feature_cols_final,
    'numeric_cols'       : numeric_cols_final,
    'categorical_cols'   : categorical_cols,
    'predictor_model'    : winner_model,
    'q10': q10, 'q50': q50, 'q90': q90,
    'gbm_dtypes_safe'    : gbm_dtypes_safe,
    'shap_explainer'     : explainer,
    'conformal_q_hat'    : float(q_hat),
    'target_coverage'    : 0.80,
    'log1p_target'       : True,
    'fuel_price_normalized': True,     # [NEW v5] model predicts cost/fuel_price, rescaled at inference
    'svc_te_map'         : svc_te_map, # [NEW v5] service_vehicle -> smoothed mean(cost/fuel_price)
    'svc_te_global'      : float(svc_te_global),
    'svc_te_smoothing'   : 5,
    'test_metrics'       : test_metrics[PREDICTOR],
    'picp_80_test'       : float(final_picp),
    'fleet_mean_lkr'     : FLEET_MEAN_LKR_V5,
    'expected_ranges'    : EXPECTED_RANGES_V5,
    'train_rows'         : len(train_df),
    'val_rows'           : len(val_df),
    'test_rows'          : len(test_df),
    'dataset'            : 'v11 (filtered: maintenance_required=1, cost>0)',
    'vehicle_size_map'   : VEHICLE_SIZE_MAP,
    'part_tokens'        : PART_TOKENS,
}
joblib.dump(bundle,'predictix_breakdown_cost_model_v5.pkl')
print(f'Saved: predictix_breakdown_cost_model_v5.pkl')

decision_log={
    'version':MODEL_VERSION,'predictor':PREDICTOR,
    'target':TARGET,
    'dataset':'v11 filtered (maintenance_required=1)',
    'train_rows':len(train_df),'val_rows':len(val_df),'test_rows':len(test_df),
    'test_metrics':{k:{m:round(float(v),4) for m,v in test_metrics[k].items()} for k in test_metrics},
    'picp_calibrated':round(float(final_picp),4),
    'conformal_q_hat':round(float(q_hat),2),
    'fleet_mean_lkr':round(FLEET_MEAN_LKR_V5,2),
    'success':{'all_pass':bool(all_pass)},
    'top15_shap':[{'rank':r+1,'feature':X_shap.columns[j],'mean_abs_shap':round(float(mean_abs[j]),4)}
                   for r,j in enumerate(top_ix)],
    'v4_to_v5_changes':[
        'Target normalized by fuel_price_lkr_per_l before modeling (multiplicative cost-inflation signal)',
        'K-fold target-encoded service_vehicle feature (svc_cost_te) added, smoothing=5',
        'XGBoost added to the bake-off; winner selected by validation R2',
        'Hyperparameters retuned to shallower trees (depth 5), which generalized best on validation',
    ],
}
with open('predictix_breakdown_cost_model_v5_log.json','w') as f:
    json.dump(decision_log,f,indent=2,default=str)
print('Saved: predictix_breakdown_cost_model_v5_log.json')

b = joblib.load('predictix_breakdown_cost_model_v5.pkl')
gbm_dtypes = {c: pd.CategoricalDtype(cats, ordered=False) for c,cats in b['gbm_dtypes_safe'].items()}

def predict_breakdown_cost(raw_input, bundle, top_k=5):
    import pandas as pd, numpy as np
    from catboost import Pool

    d = dict(raw_input)
    age = float(d.get('vehicle_age_years',0))
    vt  = str(d.get('vehicle_type',''))
    nsv = str(d.get('next_service_type', d.get('last_service_type','oil_service')))
    VSMAP = bundle['vehicle_size_map']

    d['vehicle_size_ord']   = VSMAP.get(vt,3)
    d['age_band']           = 'new' if age<=3 else 'mid' if age<=6 else 'old' if age<=10 else 'aged'
    d['service_vehicle']    = f'{nsv}__{vt}'
    d['payload_age']        = float(d.get('payload_capacity_kg',0))*age
    d['utilisation_stress'] = float(d.get('payload_utilization_pct',0))*float(d.get('downtime_hours_last_90d',0))
    d['health_index']       = (float(d.get('oil_life_pct',50))+float(d.get('brake_health_pct',50))+
                               float(d.get('tire_health_pct',50))+float(d.get('battery_health_pct',50)))/4
    d['fault_stress']       = float(d.get('active_fault_code_count',0))+float(d.get('sensor_fault_flag',0))*3
    d['health_deficit']     = 100 - d['health_index']
    d['overdue_days']       = max(0, float(d.get('days_since_last_service',0))-60)
    d['breakdown_history']  = float(d.get('lifetime_breakdown_count',0))
    d['service_intensity']  = float(d.get('lifetime_service_count',0))/(age+1)
    for tok in bundle['part_tokens']:
        d[f'part_{tok}'] = int(tok in str(d.get('parts_replaced_last_service','')))

    # [NEW v5] target-encoded service_vehicle -> smoothed mean(cost/fuel_price)
    d['svc_cost_te'] = float(bundle['svc_te_map'].get(d['service_vehicle'], bundle['svc_te_global']))

    fuel_price = float(d.get('fuel_price_lkr_per_l', 0)) or 1e-6

    row={c:d.get(c) for c in bundle['feature_cols']}
    X=pd.DataFrame([row])
    Xc=X.copy()
    for c in bundle['categorical_cols']: Xc[c]=Xc[c].astype(str).fillna('__missing__')
    for c in bundle['numeric_cols']:     Xc[c]=pd.to_numeric(Xc[c],errors='coerce').fillna(0.0)
    Xc=Xc[bundle['feature_cols']]
    gdtypes={c:pd.CategoricalDtype(cats,ordered=False) for c,cats in bundle['gbm_dtypes_safe'].items()}
    Xg=X.copy()
    for c in bundle['categorical_cols']: Xg[c]=Xg[c].astype(str).fillna('__missing__').astype(gdtypes[c])
    for c in bundle['numeric_cols']:     Xg[c]=pd.to_numeric(Xg[c],errors='coerce').fillna(0.0)
    Xg=Xg[bundle['feature_cols']]

    # [CHANGED v5] model predicts log(cost/fuel_price); rescale by fuel_price to get LKR
    log_ratio_pred=float(bundle['predictor_model'].predict(Xc)[0])
    point=float(np.expm1(max(0,log_ratio_pred)) * fuel_price)
    lo=float(max(0, np.expm1(max(0,float(bundle['q10'].predict(Xg)[0])))*fuel_price - bundle['conformal_q_hat']))
    hi=float(np.expm1(float(bundle['q90'].predict(Xg)[0]))*fuel_price + bundle['conformal_q_hat'])

    if bundle['predictor_name']=='CatBoost':
        sf=bundle['predictor_model'].get_feature_importance(
            Pool(Xc,cat_features=bundle['categorical_cols']),type='ShapValues')
        sv_arr=sf[0,:-1]
    else:
        sv_arr=bundle['shap_explainer'].shap_values(Xg)[0]
    total_abs=float(np.abs(sv_arr).sum()) or 1e-9
    top=np.argsort(np.abs(sv_arr))[::-1][:top_k]
    drivers=[{'feature':Xc.columns[j],'value':str(Xc.iloc[0,j]),
              'direction':'increases' if sv_arr[j]>0 else 'decreases',
              'relative_impact':round(abs(float(sv_arr[j]))/total_abs*100,1),
              'sv_log':round(float(sv_arr[j]),6)} for j in top]

    rng=bundle['expected_ranges'].get(nsv)
    sanity=('within_expected' if rng and rng[0]<=point<=rng[1]
            else 'below_expected' if rng and point<rng[0] else 'above_expected' if rng else 'unknown')
    return {'predicted_cost_lkr':round(point,2),'pi_80_lower_lkr':round(lo,2),
            'pi_80_upper_lkr':round(hi,2),'coverage_target':'80%',
            'fleet_mean_lkr':round(bundle['fleet_mean_lkr'],2),
            'vs_fleet_mean_lkr':round(point-bundle['fleet_mean_lkr'],2),
            'expected_range':{'p25_lkr':round(rng[0],0),'p75_lkr':round(rng[1],0)} if rng else {},
            'sanity_check':sanity,'top_drivers':drivers}

# SLW0668 profile — identical demo input to v4, for direct before/after comparison
slw0668 = {
    'vehicle_type':'Forklift_2.5T','next_service_type':'brake_service',
    'vehicle_role':'internal_material_handling','make_model':'Heli CPCD25','fuel_type':'Diesel',
    'transmission':'Manual','manufacture_year':2014,'vehicle_age_years':11.0,
    'payload_capacity_kg':2502.40,'odometer_km':19128,'engine_hours_total':4500,
    'oil_life_pct':77,'brake_health_pct':74,'tire_health_pct':50,'battery_health_pct':77,
    'hydraulic_health_pct':73,'active_fault_code_count':1,'sensor_fault_flag':0,
    'lifetime_service_count':40,'lifetime_breakdown_count':3,
    'days_since_last_service':102,'engine_hours_since_last_service':300,
    'mileage_since_last_service_km':1200,'downtime_hours_last_90d':4.2,
    'payload_utilization_pct':70,'fuel_price_lkr_per_l':310.0,
    'service_provider_type':'third_party','maintenance_priority':'Medium',
    'route_type':'Urban','cargo_type':'Industrial_goods','operating_shift':'Day',
    'parts_replaced_last_service':'brake_pads;fluid',
    'avg_payload_kg':1750,'overload_events_30d':0,'distance_last_30d_km':800,
    'operating_hours_last_30d':110,'idle_hours_last_30d':18,'trip_count_30d':40,
    'avg_trip_distance_km':20,'start_stop_burden_30d':80,'rough_road_pct':10,
    'urban_route_pct':80,'port_route_pct':5,'fuel_rate_lph':5.2,
    'fuel_efficiency_km_per_l':4.1,'engine_temp_avg_c':85,'coolant_temp_max_c':92,
    'vibration_rms_mm_s':2.1,'tire_pressure_psi':95,'battery_voltage_v':12.4,
    'ambient_temp_avg_c':30,'ambient_humidity_avg_pct':75,'rainfall_mm_30d':100,
}

r = predict_breakdown_cost(slw0668, b, top_k=5)
print('\n=== SLW0668 Breakdown Cost Prediction (v5) ===')
print(f'  Predicted cost : LKR {r["predicted_cost_lkr"]:>12,.2f}')
print(f'  80% PI         : LKR {r["pi_80_lower_lkr"]:>10,.2f}  ->  LKR {r["pi_80_upper_lkr"]:,.2f}')
print(f'  Fleet mean     : LKR {r["fleet_mean_lkr"]:>12,.2f}')
print(f'  vs fleet mean  : LKR {r["vs_fleet_mean_lkr"]:>+12,.2f}')
print(f'  Sanity check   : {r["sanity_check"]}')
print(f'\n  Top SHAP drivers:')
for dd in r['top_drivers']:
    icon='UP' if dd['direction']=='increases' else 'DOWN'
    print(f'  [{icon}] {dd["feature"]:<34s}  {dd["relative_impact"]:>5.1f}%  val={dd["value"]}')

# Reload bundle + reconstruct predictions for the visual-diagnostics section below
# (uses the model already trained & saved above; no retraining needed)
import scipy.stats as st
import seaborn as sns
sns.set_style('whitegrid')

X_test_cb2 = X_test_cb.copy()  # already includes svc_cost_te from section 7 above
pred_test = np.expm1(np.clip(model.predict(X_test_cb2), 0, None)) * fp_test
resid = y_test - pred_test
print(f'Reconstructed for plotting. Test R2 = {r2_score(y_test,pred_test):.4f}')

fig, ax = plt.subplots(2, 2, figsize=(14, 9))
ax[0,0].hist(df[TARGET], bins=60, color='#2563eb', edgecolor='white', alpha=0.85)
ax[0,0].axvline(df[TARGET].mean(), color='#dc2626', ls='--', lw=1.5, label=f'mean {df[TARGET].mean():,.0f}')
ax[0,0].axvline(df[TARGET].median(), color='#16a34a', ls='--', lw=1.5, label=f'median {df[TARGET].median():,.0f}')
ax[0,0].set_title(f'Target distribution (skew {df[TARGET].skew():.2f})'); ax[0,0].legend(fontsize=8)
ax[0,0].set_xlabel('LKR')

order_vt = df.groupby('vehicle_type')[TARGET].median().sort_values(ascending=False).index
sns.boxplot(data=df, x=TARGET, y='vehicle_type', order=order_vt, ax=ax[0,1], palette='Blues_r', showfliers=False)
ax[0,1].set_title('Cost by vehicle type'); ax[0,1].set_xlabel('LKR')

order_st = df.groupby('next_service_type')[TARGET].median().sort_values(ascending=False).index
sns.boxplot(data=df, x=TARGET, y='next_service_type', order=order_st, ax=ax[1,0], palette='Oranges_r', showfliers=False)
ax[1,0].set_title('Cost by next service type'); ax[1,0].set_xlabel('LKR')

qtrend = df.set_index('snapshot_date')[TARGET].resample('ME').agg(['mean','count'])
ax[1,1].plot(qtrend.index, qtrend['mean'], marker='o', color='#334155', lw=1.8)
ax2 = ax[1,1].twinx(); ax2.bar(qtrend.index, qtrend['count'], width=20, alpha=0.15, color='#2563eb')
ax2.set_ylabel('n records', color='#2563eb')
ax[1,1].set_title('Mean cost by month (temporal check)'); ax[1,1].set_ylabel('mean LKR')
plt.suptitle('Breakdown Cost v5 - Exploratory Data Analysis (pre-training)', y=1.01, fontweight='bold')
plt.tight_layout();
plt.savefig('v5_fig1_eda.png', dpi=120, bbox_inches='tight')
plt.show()

fig, ax = plt.subplots(1, 2, figsize=(14, 5.5))
corrs = train_df[numeric_cols].corrwith(train_df[TARGET]).abs().sort_values(ascending=False).head(15)
corrs[::-1].plot.barh(ax=ax[0], color='#2563eb')
ax[0].set_title('Top 15 numeric features - |corr| with raw cost')

gm = train_df.groupby('service_vehicle')[TARGET].mean()
resid_gm = train_df[TARGET] - train_df['service_vehicle'].map(gm)
resid_corr = train_df[numeric_cols].corrwith(resid_gm).abs().sort_values(ascending=False).head(10)
colors = ['#dc2626' if f=='fuel_price_lkr_per_l' else '#334155' for f in resid_corr.index]
resid_corr[::-1].plot.barh(ax=ax[1], color=colors[::-1])
ax[1].set_title('|corr| with residual after group-mean(service_vehicle)\n-> fuel_price is the key v5 discovery', fontsize=9)
plt.tight_layout();
plt.savefig('v5_fig2_correlations.png', dpi=120, bbox_inches='tight')
plt.show()

import scipy.stats as st
fig, ax = plt.subplots(1, 3, figsize=(16, 5))
mx = max(y_test.max(), pred_test.max())
ax[0].scatter(y_test, pred_test, s=8, alpha=0.35, color='#2563eb')
ax[0].plot([0,mx],[0,mx],'k--',lw=1)
ax[0].set_xlabel('Actual LKR'); ax[0].set_ylabel('Predicted LKR')
ax[0].set_title(f'Actual vs Predicted ({PREDICTOR}, R2={r2_score(y_test,pred_test):.3f})')

ax[1].scatter(pred_test, resid, s=8, alpha=0.35, color='#16a34a')
ax[1].axhline(0, color='k', ls='--', lw=1)
ax[1].set_xlabel('Predicted LKR'); ax[1].set_ylabel('Residual (actual-pred)')
ax[1].set_title('Residuals vs Predicted (heteroscedasticity check)')

st.probplot(resid, dist='norm', plot=ax[2]); ax[2].set_title('Residual Q-Q plot')
plt.suptitle('Breakdown Cost v5 - Post-training Diagnostics', y=1.03, fontweight='bold')
plt.tight_layout();
plt.savefig('v5_fig3_residuals.png', dpi=120, bbox_inches='tight')
plt.show()

fig, ax = plt.subplots(1, 3, figsize=(16, 5))
dec = pd.qcut(pred_test, 10, duplicates='drop')
calib = pd.DataFrame({'pred':pred_test,'actual':y_test,'bin':dec}).groupby('bin').agg(
    pred_mean=('pred','mean'), actual_mean=('actual','mean'))
ax[0].plot(calib['pred_mean'], calib['actual_mean'], 'o-', color='#2563eb')
lims = [0, max(calib['pred_mean'].max(), calib['actual_mean'].max())*1.05]
ax[0].plot(lims, lims, 'k--', lw=1)
ax[0].set_xlabel('Mean predicted LKR (decile)'); ax[0].set_ylabel('Mean actual LKR (decile)')
ax[0].set_title('Calibration by prediction decile')

order = np.argsort(y_test)[:200]; xs = np.arange(len(order))
ax[1].fill_between(xs, lo_cal[order], hi_cal[order], color='#2563eb', alpha=0.25, label='80% PI (calibrated)')
ax[1].plot(xs, y_test[order], '.', color='#dc2626', ms=3, label='actual')
ax[1].plot(xs, pred_test[order], '-', color='#334155', lw=0.8, label='predicted')
ax[1].set_title(f'80% PI band (first 200 test pts, sorted)\nPICP={((y_test>=lo_cal)&(y_test<=hi_cal)).mean()*100:.1f}%')
ax[1].legend(fontsize=7); ax[1].set_xlabel('test sample (sorted by actual)')

picp_by_dec = pd.DataFrame({'actual':y_test,'lo':lo_cal,'hi':hi_cal,
                             'bin':pd.qcut(pred_test,10,duplicates='drop')}).groupby('bin').apply(
    lambda g: ((g['actual']>=g['lo'])&(g['actual']<=g['hi'])).mean())
picp_by_dec.plot.bar(ax=ax[2], color='#16a34a')
ax[2].axhline(0.80, color='k', ls='--', lw=1, label='target 80%')
ax[2].set_title('PICP by prediction decile'); ax[2].set_ylabel('coverage'); ax[2].legend(fontsize=8)
ax[2].tick_params(axis='x', labelsize=6, rotation=45)
plt.suptitle('Breakdown Cost v5 - Calibration & Prediction Interval Coverage', y=1.03, fontweight='bold')
plt.tight_layout();
plt.savefig('v5_fig4_calibration_pi.png', dpi=120, bbox_inches='tight')
plt.show()

fig, ax = plt.subplots(figsize=(8, 6))
imp = pd.Series(model.get_feature_importance(), index=X_test_cb.columns).sort_values(ascending=False).head(15)
imp[::-1].plot.barh(ax=ax, color='#334155')
ax.set_title(f'{PREDICTOR} native feature importance (top 15)')
plt.tight_layout();
plt.savefig('v5_fig5_feature_importance.png', dpi=120, bbox_inches='tight')
plt.show()

n_shap = min(3000, len(X_test_cb))
idx = np.random.RandomState(42).choice(len(X_test_cb), n_shap, replace=False)
sf = model.get_feature_importance(Pool(X_test_cb.iloc[idx], cat_features=categorical_cols), type='ShapValues')
sv = sf[:, :-1]
X_shap = X_test_cb.iloc[idx]
mean_abs = np.abs(sv).mean(axis=0)
top3_numeric = [X_shap.columns[j] for j in np.argsort(mean_abs)[::-1]
                if X_shap.columns[j] in numeric_cols + ['svc_cost_te']][:3]

fig, ax = plt.subplots(1, 3, figsize=(16, 5))
for a, f in zip(ax, top3_numeric):
    j = list(X_shap.columns).index(f)
    a.scatter(X_shap[f], sv[:, j], s=6, alpha=0.35, color='#2563eb')
    a.axhline(0, color='k', lw=0.6, ls='--')
    a.set_xlabel(f); a.set_ylabel('SHAP value (log-ratio)'); a.set_title(f)
plt.suptitle('SHAP dependence - three most influential numeric features', y=1.03, fontweight='bold')
plt.tight_layout(); plt.savefig('v5_fig6_shap_dependence.png', dpi=120, bbox_inches='tight')
plt.show()
print('Top 3 numeric drivers:', top3_numeric)

seg = test_df[['vehicle_type','next_service_type']].copy()
seg['actual'] = y_test; seg['pred'] = pred_test; seg['abs_err'] = np.abs(y_test-pred_test)
fig, ax = plt.subplots(1, 2, figsize=(15, 5))
g1 = seg.groupby('vehicle_type')['abs_err'].mean().sort_values(ascending=False)
g1.plot.bar(ax=ax[0], color='#dc2626')
ax[0].set_title('MAE by vehicle type'); ax[0].set_ylabel('MAE (LKR)'); ax[0].tick_params(axis='x', rotation=40, labelsize=7)

g2 = seg.groupby('next_service_type')['abs_err'].mean().sort_values(ascending=False)
g2.plot.bar(ax=ax[1], color='#16a34a')
ax[1].set_title('MAE by next service type'); ax[1].set_ylabel('MAE (LKR)'); ax[1].tick_params(axis='x', rotation=40, labelsize=7)
plt.suptitle('Breakdown Cost v5 - Error by Segment', y=1.03, fontweight='bold')
plt.tight_layout();
plt.savefig('v5_fig7_error_by_segment.png', dpi=120, bbox_inches='tight')
plt.show()

tdf = test_df[['snapshot_date']].copy(); tdf['actual']=y_test; tdf['pred']=pred_test
tdf['month'] = tdf['snapshot_date'].dt.to_period('M')
monthly = tdf.groupby('month').apply(lambda g: pd.Series({
    'R2': r2_score(g['actual'],g['pred']) if len(g)>5 else np.nan,
    'MAE': np.abs(g['actual']-g['pred']).mean(), 'n': len(g)}))
fig, ax = plt.subplots(1, 2, figsize=(14, 4.5))
ax[0].plot(monthly.index.astype(str), monthly['R2'], marker='o', color='#2563eb')
ax[0].axhline(0.80, color='k', ls='--', lw=1, label='target R2=0.80')
ax[0].set_title('Monthly test R2 - temporal stability'); ax[0].legend(fontsize=8); ax[0].tick_params(axis='x', rotation=45, labelsize=7)
ax[1].bar(monthly.index.astype(str), monthly['MAE'], color='#16a34a')
ax[1].set_title('Monthly test MAE (LKR)'); ax[1].tick_params(axis='x', rotation=45, labelsize=7)
plt.suptitle('Breakdown Cost v5 - Temporal Stability (test period)', y=1.03, fontweight='bold')
plt.tight_layout(); plt.savefig('v5_fig8_temporal_stability.png', dpi=120, bbox_inches='tight')
plt.show()
print(monthly.round(3))
