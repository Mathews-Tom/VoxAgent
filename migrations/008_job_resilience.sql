CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_conversation_id_unique
    ON leads(conversation_id);
