import re

def classify_test(question: str):
    q = question.strip().lower()
    
    # 1. Fast-path: Data inspection & specific ticket/asset lookups -> DATABASE
    DATA_TRIGGERS = (
        "show me", "details of", "status of", "info on", "how many", "count of",
        "number of", "list of", "breakdown", "find ticket", "find asset",
        "search ticket", "search asset"
    )
    if any(dt in q for dt in DATA_TRIGGERS) or re.search(r"\b(tkt-\d+|t-\d+|#\d+)\b", q):
        return "DATABASE"

    # Fast-path: navigation phrases — "open X", "go to X", "take me to X", "navigate to X"
    NAV_TRIGGERS = (
        "open ", "go to ", "take me to ", "navigate to ",
        "bring me to ", "launch ", "redirect to ", "i want to go to ",
        "switch to ", "jump to ",
    )
    NAV_SUBJECTS = (
        "asset", "ticket", "dashboard", "report", "warehouse", "user",
        "profile", "setting", "helpdesk", "help desk", "notification",
        "prediction", "cost", "fleet", "home", "overview",
    )
    if any(q.startswith(t) for t in NAV_TRIGGERS) and any(s in q for s in NAV_SUBJECTS):
        return "NAVIGATION"

    return "OTHER"

queries = [
    "Show me the details of ticket T-0936.",
    "show me the tickets",
    "open tickets",
    "take me to settings",
    "how many open tickets",
    "details of T-0936"
]

for q in queries:
    print(f"'{q}' -> {classify_test(q)}")
