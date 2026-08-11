import sqlalchemy
from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://postgres.ulpjoljukculqqrwlwup:udCV%40bTGj.Ah38L@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres')

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS public.faqs (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    question text NOT NULL,
    answer text NOT NULL,
    category text NOT NULL DEFAULT 'general',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.faqs ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='faqs' AND policyname='FAQs are viewable by everyone'
  ) THEN
    CREATE POLICY "FAQs are viewable by everyone"
      ON public.faqs FOR SELECT USING (true);
  END IF;
END $$;
"""

FAQS = [
    # ─── Authentication & Account ───
    ("how to log out", "To log out, click the logout option in your user menu or sidebar. You'll be safely signed out.", "account"),
    ("how to change my password", "There is currently no option to change your password directly in the application. Please contact your system administrator at neuromindspredictix@gmail.com to request a password change.", "account"),
    ("how to reset my password", "If you've forgotten your password, please contact support at neuromindspredictix@gmail.com to request a password reset.", "account"),
    ("i forgot my password", "Please contact the administrators at neuromindspredictix@gmail.com and they will reset your password for you.", "account"),
    ("how to update my profile", "To update your profile information (like your name or phone number), please contact your system administrator at neuromindspredictix@gmail.com.", "account"),
    ("how to change my email", "Email changes require admin assistance. Please contact your system administrator at neuromindspredictix@gmail.com with your request.", "account"),
    ("what is my role", "Your role determines your permissions in PredictiX. Common roles include 'User' (standard access), 'Admin' (management access), and 'Super Admin'.", "account"),
    ("how to enable two factor authentication", "Two-factor authentication is managed by administrators. Please contact neuromindspredictix@gmail.com to request 2FA setup.", "account"),
    ("how to deactivate my account", "Account deactivation is handled by administrators. Please contact neuromindspredictix@gmail.com with your request.", "account"),

    # ─── Tickets / Helpdesk ───
    ("how to open a ticket", "To open a new support ticket, navigate to the Tickets or Helpdesk section and click the button to create a new ticket. Fill in the details and submit.", "tickets"),
    ("how to view my tickets", "Go to the Tickets section from the navigation menu to see all tickets relevant to your account.", "tickets"),
    ("what are ticket priorities", "PredictiX uses priority levels (e.g., High, Medium, Low) to indicate the urgency of a ticket.", "tickets"),
    ("what are ticket statuses", "Tickets can have various statuses such as Open, In Progress, Resolved, and Closed, indicating their current stage.", "tickets"),
    ("what is a ticket number", "Each ticket gets a unique identifier automatically when created, which you can use to reference that specific issue.", "tickets"),

    # ─── Assets ───
    ("how to view assets", "Navigate to the Assets section from the navigation menu to see the list of registered assets.", "assets"),
    ("how to search for an asset", "On the Assets page, use the search bar or filters to find specific assets by name, type, or status.", "assets"),
    ("what is an asset status", "Assets have statuses indicating if they are Active, Inactive, Under Maintenance, etc.", "assets"),

    # ─── AI Predictions ───
    ("how does failure prediction work", "PredictiX uses machine learning to analyze your asset data and predict the likelihood of failure, helping you plan proactive maintenance.", "predictions"),
    ("how to view predictions", "You can view AI predictions in the Reports or Dashboard section. Assets with high failure probabilities will be flagged.", "predictions"),
    ("what is a failure probability score", "The failure probability score indicates how likely an asset is to fail soon. Higher scores mean greater risk.", "predictions"),
    ("what are critical alerts", "Critical alerts are triggered when an asset is at high risk of failure and requires attention.", "predictions"),

    # ─── Navigation & System ───
    ("how to navigate to dashboard", "Click 'Dashboard' in the navigation menu. The Dashboard shows your live KPIs and system overview.", "navigation"),
    ("how to navigate to tickets", "Click 'Tickets' or 'Helpdesk' in the navigation menu.", "navigation"),
    ("how to navigate to assets", "Click 'Assets' in the navigation menu.", "navigation"),
    ("what is predictix", "PredictiX is an AI-powered Smart Asset Management System that helps organizations track assets, manage maintenance tickets, and predict equipment failures.", "general"),
    ("how to contact support", "You can reach the PredictiX support team by emailing neuromindspredictix@gmail.com.", "general"),
    ("how to report a bug", "If you find a bug, please email neuromindspredictix@gmail.com with a description of the issue.", "general"),
    ("is my data secure in predictix", "Yes! PredictiX uses secure data storage and role-based access control to ensure your data is safe.", "general"),
    ("how to use the chatbot", "Just type your question naturally in the chat box! You can ask about your data, system navigation, or general help.", "general"),
    ("how to access help", "You can ask me anything in this chat, or email neuromindspredictix@gmail.com for further assistance.", "general")
]

with engine.connect() as conn:
    conn.execute(text(CREATE_TABLE))
    conn.commit()
    print(f"Table created/verified.")

    # Truncate the table to remove old incorrect FAQs
    conn.execute(text("TRUNCATE TABLE public.faqs"))
    conn.commit()

    # Insert FAQs
    inserted = 0
    for question, answer, category in FAQS:
        conn.execute(
            text("INSERT INTO public.faqs (question, answer, category, is_active) VALUES (:q, :a, :c, true) ON CONFLICT DO NOTHING"),
            {"q": question, "a": answer, "c": category}
        )
        inserted += 1

    conn.commit()
    count = conn.execute(text("SELECT COUNT(*) FROM public.faqs")).scalar()
    print(f"Seeded {inserted} FAQs. Total in table: {count}")

