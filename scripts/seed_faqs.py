import asyncio
from app.db.supabase_client import supabase

def seed():
    # 1. Delete all existing FAQs
    print("Deleting old FAQs...")
    res = supabase.from_("faqs").select("id").execute()
    ids = [row["id"] for row in res.data]
    if ids:
        for _id in ids:
            supabase.from_("faqs").delete().eq("id", _id).execute()
        print(f"Deleted {len(ids)} FAQs.")

    # 2. Define accurate FAQs
    faqs = [
        # --- Authentication & Profiles ---
        {"category": "Account Access", "question": "How do I log into PredictiX?", "answer": "Navigate to the main login page and enter your registered email address and password. If your company uses SSO, click the 'Continue with SSO' button.", "is_active": True},
        {"category": "Account Access", "question": "Can I change my profile picture?", "answer": "Yes, navigate to 'My Profile' from the top right user menu and upload a new avatar image. Supported formats are JPG and PNG.", "is_active": True},
        {"category": "Account Access", "question": "How do I update my contact information?", "answer": "Go to 'My Profile' to update your phone number, department, and preferred contact method.", "is_active": True},
        {"category": "Account Access", "question": "What happens if I forget my password?", "answer": "Click 'Forgot Password' on the login screen. You will receive an email with a secure, time-sensitive reset link.", "is_active": True},
        {"category": "Account Access", "question": "How do I switch between dark mode and light mode?", "answer": "Click the sun/moon icon located in the top right navigation bar to toggle the theme across the entire application.", "is_active": True},
        {"category": "Account Access", "question": "Can I have multiple active sessions?", "answer": "Yes, PredictiX supports multiple active sessions across different devices (e.g., your laptop and mobile phone).", "is_active": True},
        {"category": "Account Access", "question": "How do I log out of all devices?", "answer": "In your 'Account Settings' under 'Security', click 'Revoke All Sessions' to log out everywhere instantly.", "is_active": True},
        {"category": "Account Access", "question": "What are the password requirements?", "answer": "Passwords must be at least 8 characters long and contain at least one uppercase letter, one lowercase letter, and one number.", "is_active": True},

        # --- Dashboard & UI ---
        {"category": "General", "question": "What is the PredictiX Dashboard?", "answer": "The Dashboard provides a high-level overview of your assigned assets, active tickets, and system health metrics using interactive charts.", "is_active": True},
        {"category": "General", "question": "How do I return to the main dashboard?", "answer": "Click the PredictiX logo in the top left corner or the 'Dashboard' link in the left sidebar at any time.", "is_active": True},
        {"category": "General", "question": "Can I collapse the sidebar?", "answer": "Yes, use the toggle icon at the bottom of the left sidebar to collapse it and maximize your screen real estate.", "is_active": True},
        {"category": "General", "question": "Is PredictiX mobile-friendly?", "answer": "Yes! The interface is fully responsive and will adapt perfectly to tablets and mobile phones.", "is_active": True},

        # --- Asset Management (User) ---
        {"category": "Assets", "question": "How do I see assets assigned to me?", "answer": "Click on 'My Assets' in the sidebar to view a grid or list of all hardware and software assigned specifically to your profile.", "is_active": True},
        {"category": "Assets", "question": "What information is tracked for my assets?", "answer": "You can view the asset name, serial number, purchase date, warranty status, AI-predicted health score, and maintenance history.", "is_active": True},
        {"category": "Assets", "question": "How do I request a new asset?", "answer": "You must create a Helpdesk ticket categorized as 'Hardware Request' or 'Software Request' and specify your requirements.", "is_active": True},
        {"category": "Assets", "question": "What does the AI Health Score mean?", "answer": "PredictiX uses machine learning to analyze the age, maintenance logs, and usage of your asset to predict its remaining lifespan. A score below 40 indicates high risk of failure.", "is_active": True},
        {"category": "Assets", "question": "How do I report that an asset is broken?", "answer": "Open a ticket, set the category to 'Hardware Support', and link the specific asset to the ticket so IT knows exactly which machine is faulty.", "is_active": True},
        {"category": "Assets", "question": "Can I view the maintenance history of my laptop?", "answer": "Yes, click on any assigned asset to view its 'Maintenance Logs' section, which shows all past repairs and services.", "is_active": True},
        {"category": "Assets", "question": "How do I return an asset?", "answer": "Submit a 'Return Asset' ticket. IT will process the unassignment and arrange for physical collection.", "is_active": True},

        # --- Ticketing System (User) ---
        {"category": "Ticketing", "question": "How do I create a new support ticket?", "answer": "Click the 'New Ticket' button in the sidebar or from the Tickets page. Fill out the title, description, category, and priority.", "is_active": True},
        {"category": "Ticketing", "question": "What priority level should I choose?", "answer": "Low: Non-urgent inquiries. Medium: Standard requests. High: Important functions are impaired. Critical: Work-stopping emergencies (entire system down).", "is_active": True},
        {"category": "Ticketing", "question": "Can I attach files to my ticket?", "answer": "Yes, you can upload screenshots, PDFs, and log files using the attachment dropzone when creating or updating a ticket.", "is_active": True},
        {"category": "Ticketing", "question": "How do I reply to an IT technician?", "answer": "Open your ticket and use the 'Comments' section at the bottom to send messages and attachments directly to the assigned technician.", "is_active": True},
        {"category": "Ticketing", "question": "Can I close my own ticket?", "answer": "Yes, if your issue resolves itself, you can open the ticket details and click 'Mark as Resolved' to close it.", "is_active": True},
        {"category": "Ticketing", "question": "How will I know when my ticket is updated?", "answer": "You will receive real-time pop-up notifications and a badge on the Notification Bell whenever a status changes or a comment is added.", "is_active": True},
        {"category": "Ticketing", "question": "Can I reopen a closed ticket?", "answer": "No, once a ticket is marked 'Closed', it is archived. However, you can reference the closed ticket ID when opening a new one.", "is_active": True},
        {"category": "Ticketing", "question": "What is the difference between 'Resolved' and 'Closed'?", "answer": "IT marks a ticket 'Resolved' when they believe the fix is applied. It automatically transitions to 'Closed' after 3 days if you don't object.", "is_active": True},
        {"category": "Ticketing", "question": "Can I search my past tickets?", "answer": "Yes, the Tickets dashboard has a search bar and filters for status, priority, and date ranges.", "is_active": True},

        # --- Notifications ---
        {"category": "Notifications", "question": "Where do I see my notifications?", "answer": "Click the Bell icon in the top right corner to open the Notification Center and view all recent alerts.", "is_active": True},
        {"category": "Notifications", "question": "How do I stop the popup toasts from showing?", "answer": "Currently, critical system toasts cannot be disabled as they ensure you see important updates, but they automatically dismiss after a few seconds.", "is_active": True},
        {"category": "Notifications", "question": "Can I pin important notifications?", "answer": "Yes! Hover over a notification in the bell dropdown and click the 'Pin' icon to keep it at the top of your list.", "is_active": True},
        {"category": "Notifications", "question": "How do I mark all notifications as read?", "answer": "Open the Notification Center and click the 'Mark all read' button at the top right of the panel.", "is_active": True},
        {"category": "Notifications", "question": "Can I delete old notifications?", "answer": "Yes, hover over any notification and click the 'Trash' icon to permanently remove it from your history.", "is_active": True},
        {"category": "Notifications", "question": "Why did a notification give me a 'Show Ticket' button?", "answer": "The system automatically detects if a notification is related to a specific item (like a ticket or asset) and provides a direct quick-link to it.", "is_active": True},

        # --- AI Chatbot & Agentic Features ---
        {"category": "AI Assistant", "question": "What is the PredictiX AI Chatbot?", "answer": "Our chatbot uses Advanced Agentic AI to help you troubleshoot issues instantly without waiting for human IT staff.", "is_active": True},
        {"category": "AI Assistant", "question": "How do I access the AI Chatbot?", "answer": "Click the chat bubble icon in the bottom right corner of the screen to open the assistant.", "is_active": True},
        {"category": "AI Assistant", "question": "Can the AI check my asset's health?", "answer": "Yes, the AI has direct integration with the database. You can ask 'Is my laptop healthy?' and it will query the predictive maintenance model.", "is_active": True},
        {"category": "AI Assistant", "question": "Can the AI automatically create a ticket for me?", "answer": "Absolutely. If the AI determines your issue requires human intervention, it can draft and submit a ticket on your behalf.", "is_active": True},
        {"category": "AI Assistant", "question": "How does the AI know my ticket priorities?", "answer": "The AI uses sentiment analysis and historical data to analyze your prompt and automatically assign the correct priority to your issue.", "is_active": True},
        {"category": "AI Assistant", "question": "Does the AI read my past tickets?", "answer": "Yes, the AI can query your past resolved tickets to see if your current issue is a recurring problem.", "is_active": True},
        {"category": "AI Assistant", "question": "What should I do if the AI gives incorrect advice?", "answer": "The AI is an assistant, but you can always bypass it by manually opening a ticket to speak directly to an IT administrator.", "is_active": True},

        # --- Asset Management (Admin Only Features) ---
        {"category": "Admin Features", "question": "How do I add a new asset to the inventory?", "answer": "Navigate to the Admin 'Assets' page and click 'Add Asset'. Enter the serial number, model, purchase date, and specs.", "is_active": True},
        {"category": "Admin Features", "question": "How do I assign an asset to a user?", "answer": "Open the asset details, click 'Assign', and select the user from the dropdown menu. They will be notified immediately.", "is_active": True},
        {"category": "Admin Features", "question": "Can I bulk import assets?", "answer": "Yes, the system supports CSV imports for onboarding large quantities of hardware simultaneously.", "is_active": True},
        {"category": "Admin Features", "question": "How do I log a maintenance event?", "answer": "Select the asset, click 'Log Maintenance', and record the service details. This data trains our predictive AI models.", "is_active": True},
        {"category": "Admin Features", "question": "What happens when an asset's AI Health Score drops below 30?", "answer": "The system flags the asset as 'Critical' and will proactively recommend scheduling a replacement before total failure occurs.", "is_active": True},
        {"category": "Admin Features", "question": "How do I generate an Asset Report?", "answer": "Click 'Generate Report' on any asset. The system compiles its specs, maintenance history, and AI health predictions into a printable PDF.", "is_active": True},
        {"category": "Admin Features", "question": "Can I track software licenses as assets?", "answer": "Yes, when creating an asset, change the type from 'Hardware' to 'Software' to track license keys and expiration dates.", "is_active": True},

        # --- User Management (Admin Only) ---
        {"category": "Admin Features", "question": "How do I invite a new user?", "answer": "Go to the Admin 'Users' dashboard, click 'Add User', and enter their details. They will receive an email invitation.", "is_active": True},
        {"category": "Admin Features", "question": "Can I deactivate a user instead of deleting them?", "answer": "Yes. Deactivating a user revokes their login access but preserves all their historical tickets and asset assignments for auditing purposes.", "is_active": True},
        {"category": "Admin Features", "question": "How do I see what assets a user has?", "answer": "In the Users table, click the 'View Assets' button next to their name to see a detailed modal of all hardware assigned to them.", "is_active": True},
        {"category": "Admin Features", "question": "Can I promote a standard user to an Admin?", "answer": "Yes, edit the user's profile and change their Role dropdown from 'User' to 'Admin'.", "is_active": True},
        {"category": "Admin Features", "question": "How do I unassign all assets during an employee offboarding?", "answer": "You can go to the user's asset view and systematically click 'Unassign' on each device, which moves the assets back to available inventory.", "is_active": True},

        # --- Ticketing (Admin Only Features) ---
        {"category": "Admin Features", "question": "How do I assign a ticket to myself?", "answer": "Open the ticket details and change the 'Assignee' field to your own name.", "is_active": True},
        {"category": "Admin Features", "question": "Can I change a ticket's priority if the user exaggerated it?", "answer": "Yes, Admins have full rights to downgrade or upgrade a ticket's priority level based on actual SLA requirements.", "is_active": True},
        {"category": "Admin Features", "question": "Is there a Kanban board for tickets?", "answer": "Currently, tickets are displayed in an advanced data table with powerful sorting and filtering capabilities rather than a Kanban view.", "is_active": True},
        {"category": "Admin Features", "question": "How do I view ticket resolution metrics?", "answer": "The Admin Dashboard provides charts detailing average resolution times and ticket volume categorized by priority.", "is_active": True},
        {"category": "Admin Features", "question": "Can I delete a spam ticket?", "answer": "Yes, Admins can permanently delete tickets. Standard users can only view or close them.", "is_active": True},

        # --- Helpdesk FAQ Management (Admin) ---
        {"category": "Admin Features", "question": "How do I publish a new FAQ?", "answer": "Go to the Helpdesk page as an Admin, type the question and answer in the 'Add New FAQ' sidebar, and click Publish.", "is_active": True},
        {"category": "Admin Features", "question": "Can I edit an existing FAQ?", "answer": "Yes, click the 'Edit' button next to any FAQ card to update its text. Changes are instantly visible to all users.", "is_active": True},
        {"category": "Admin Features", "question": "How do I delete outdated FAQs?", "answer": "Click the red 'Delete' trash can icon on the FAQ card. This action cannot be undone.", "is_active": True},

        # --- Miscellaneous & System Architecture ---
        {"category": "System Info", "question": "What powers the PredictiX AI?", "answer": "The predictive engine utilizes Python-based Scikit-learn (RandomForest) alongside Joblib, and the conversational AI leverages advanced LLMs via GROQ.", "is_active": True},
        {"category": "System Info", "question": "Is the application secure?", "answer": "Yes, PredictiX uses robust JWT authentication, PostgreSQL Row-Level Security via Supabase, and HTTPS encryption.", "is_active": True},
        {"category": "System Info", "question": "Where is the data stored?", "answer": "Data is securely hosted in cloud PostgreSQL databases managed by Supabase, ensuring high availability and automated backups.", "is_active": True},
        {"category": "System Info", "question": "What happens if the AI prediction model fails to load?", "answer": "The system has built-in fallbacks. If the machine learning model file is unavailable, it uses a safe heuristic algorithm to estimate asset health without crashing.", "is_active": True},
        {"category": "System Info", "question": "Does the system support multiple languages?", "answer": "Currently, PredictiX is strictly localized in English.", "is_active": True},
        {"category": "System Info", "question": "What is the maximum file size for ticket attachments?", "answer": "Ticket attachments are securely processed, but extremely large files (e.g. >50MB) may be rejected depending on the storage bucket policies.", "is_active": True},
        {"category": "System Info", "question": "Can the frontend run offline?", "answer": "No, PredictiX requires an active internet connection to communicate with the FastAPI backend and real-time WebSockets.", "is_active": True},
        {"category": "System Info", "question": "How do WebSockets work in this app?", "answer": "We use persistent FastAPI WebSockets to instantly push database updates (like new tickets or profile changes) directly to your screen without requiring a page refresh.", "is_active": True},
        {"category": "System Info", "question": "Why are the popup notifications 'Glassmorphic'?", "answer": "The UI was custom-designed to be incredibly beautiful and modern, utilizing backdrop-blur and vibrant gradients to enhance user experience.", "is_active": True},
        {"category": "System Info", "question": "Can I export data to Excel?", "answer": "Yes, you can generate PDF reports for specific assets, and future updates will include direct CSV exports from data tables.", "is_active": True},
        {"category": "System Info", "question": "What happens when I click 'Send Service Reminder'?", "answer": "The system automatically drafts and dispatches an alert to the assigned user, notifying them that their hardware is due for routine maintenance.", "is_active": True},
        {"category": "System Info", "question": "How is ticket search implemented?", "answer": "The ticket tables utilize fast, client-side filtering combined with robust backend query endpoints to ensure instantaneous search results.", "is_active": True},
        {"category": "System Info", "question": "Can I customize the categories?", "answer": "Currently, categories for tickets and assets are hardcoded into the system ENUMs to ensure database consistency.", "is_active": True},
        {"category": "System Info", "question": "How do I request a new feature for PredictiX?", "answer": "Submit a ticket categorized as 'Feature Request' and provide a detailed use-case for the development team to review.", "is_active": True}
    ]

    print("Inserting new FAQs...")
    for faq in faqs:
        supabase.from_("faqs").insert(faq).execute()
    print("Seeded successfully!")

if __name__ == "__main__":
    seed()
