-- 012_correct_account_faqs.sql
--
-- Two FAQ answers no longer describe the application accurately, and the
-- chatbot answers from them:
--
--   * "how to change my password" says there is no way to change a password
--     in the app. Users now change it under Settings -> Password.
--   * "how to enable two factor authentication" implies administrators can turn
--     2FA on. PredictiX has no two-factor authentication.
--
-- Guarded by the old wording, so re-running is a no-op and an answer an admin
-- has since rewritten is left alone.

UPDATE faqs
SET answer = 'Open Settings from your profile menu and use the Password section: enter your current password, then your new password twice and select Change password. New passwords need at least 8 characters and cannot be numbers only. If you have forgotten your current password, contact the administrators at neuromindspredictix@gmail.com.',
    updated_at = now()
WHERE lower(question) = 'how to change my password'
  AND answer ILIKE 'There is currently no option to change your password%';

UPDATE faqs
SET answer = 'PredictiX does not offer two-factor authentication at the moment. Keep your account safe by using a strong password that you do not use anywhere else, and change it under Settings -> Password if you think it has been exposed.',
    updated_at = now()
WHERE lower(question) = 'how to enable two factor authentication'
  AND answer ILIKE 'Two-factor authentication is managed by administrators%';

-- Synonyms people type for three FAQs that the chatbot's semantic search
-- missed in scripts/eval_rag.py. Tags are embedded with the question and
-- answer. Only set where an admin has not already added tags.
UPDATE faqs SET tags = ARRAY['sign out', 'logout', 'log off', 'end session'], updated_at = now()
WHERE lower(question) = 'how to log out' AND (tags IS NULL OR cardinality(tags) = 0);

UPDATE faqs SET tags = ARRAY['raise a ticket', 'maintenance request', 'report an issue', 'new ticket', 'request repair'], updated_at = now()
WHERE lower(question) = 'how to open a ticket' AND (tags IS NULL OR cardinality(tags) = 0);

UPDATE faqs SET tags = ARRAY['about the app', 'what does this application do', 'purpose of the system', 'overview'], updated_at = now()
WHERE lower(question) = 'what is predictix' AND (tags IS NULL OR cardinality(tags) = 0);
