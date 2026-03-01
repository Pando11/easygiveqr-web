CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,

    -- Agent Info
    agent_name VARCHAR(255) NOT NULL,
    agent_phone VARCHAR(20) NOT NULL,
    agent_email VARCHAR(255) NOT NULL,

    -- Property Info
    property_address TEXT NOT NULL,
    contract_price DECIMAL(12,2),

    -- Contract Document
    contract_pdf_url TEXT,
    contract_s3_key VARCHAR(500),

    -- Texas Critical Dates (12 deadlines)
    effective_date DATE,
    option_fee_due_date DATE,
    earnest_due_date DATE,
    seller_disclosure_due_date DATE,
    survey_due_date DATE,
    option_period_end_date DATE,
    hoa_docs_due_date DATE,
    buyer_hoa_review_end_date DATE,
    title_commitment_due_date DATE,
    financing_approval_date DATE,
    buyer_title_objection_end_date DATE,
    closing_date DATE,

    -- Transaction Parties
    buyer_name VARCHAR(255),
    buyer_phone VARCHAR(20),
    seller_name VARCHAR(255),
    seller_phone VARCHAR(20),
    lender_name VARCHAR(255),
    lender_company VARCHAR(255),
    lender_phone VARCHAR(20),
    lender_email VARCHAR(255),
    title_company VARCHAR(255),
    title_officer_name VARCHAR(255),
    title_officer_phone VARCHAR(20),
    title_officer_email VARCHAR(255),

    -- Status Tracking
    status VARCHAR(50) DEFAULT 'NEEDS_MARGARET_REVIEW',
    -- Status values: NEEDS_MARGARET_REVIEW, ACTIVE, COMPLETED, CANCELLED

    -- Service Details
    rush_service BOOLEAN DEFAULT FALSE,
    referred_by_agent VARCHAR(255),

    -- Payment Tracking
    payment_upfront_paid BOOLEAN DEFAULT FALSE,
    payment_upfront_date TIMESTAMP,
    payment_closing_paid BOOLEAN DEFAULT FALSE,
    payment_closing_date TIMESTAMP,

    -- Agent Confirmation
    agent_confirmed_timeline BOOLEAN DEFAULT FALSE,

    -- Post-Closing
    review_requested BOOLEAN DEFAULT FALSE,
    review_requested_date TIMESTAMP,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE deadlines (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,

    -- Deadline Info
    deadline_type VARCHAR(100) NOT NULL,
    -- Types: option_fee, earnest_money, seller_disclosure, survey,
    --        option_period_end, hoa_docs, buyer_hoa_review, title_commitment,
    --        financing_approval, buyer_title_objection, closing
    deadline_date DATE NOT NULL,
    description TEXT,
    is_critical BOOLEAN DEFAULT FALSE,

    -- Reminder Tracking (4-stage)
    reminder_10d_sent BOOLEAN DEFAULT FALSE,
    reminder_10d_sent_at TIMESTAMP,
    reminder_7d_sent BOOLEAN DEFAULT FALSE,
    reminder_7d_sent_at TIMESTAMP,
    reminder_3d_sent BOOLEAN DEFAULT FALSE,
    reminder_3d_sent_at TIMESTAMP,
    reminder_1d_sent BOOLEAN DEFAULT FALSE,
    reminder_1d_sent_at TIMESTAMP,

    -- Margaret Follow-up
    margaret_called_agent BOOLEAN DEFAULT FALSE,
    margaret_call_date TIMESTAMP,

    -- Completion
    completed BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,

    -- Task Info
    task_description TEXT NOT NULL,
    task_category VARCHAR(100),
    -- Categories: contract_setup, coordination, documents, pre_closing, closing, post_closing
    due_date DATE,
    priority VARCHAR(20) DEFAULT 'medium',
    -- Priority: high, medium, low

    -- Assignment
    assigned_to VARCHAR(100) DEFAULT 'margaret',

    -- Status
    status VARCHAR(50) DEFAULT 'pending',
    -- Status: pending, in_progress, completed, not_applicable

    -- Completion
    completed BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMP,
    completed_by VARCHAR(100),
    notes TEXT,

    -- Order (for display sorting)
    display_order INT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE documents (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,

    -- Document Info
    document_type VARCHAR(100) NOT NULL,
    -- Types: contract, earnest_receipt, option_receipt, seller_disclosure,
    --        survey, hoa_docs, title_commitment, inspection_report,
    --        appraisal, loan_approval, insurance_binder, amendment,
    --        settlement_statement, other
    filename VARCHAR(255) NOT NULL,

    -- S3 Storage
    s3_key VARCHAR(500) NOT NULL,
    file_size INT,

    -- Status
    status VARCHAR(50) DEFAULT 'received',
    -- Status: received, sent_to_parties, archived

    -- Tracking
    uploaded_by VARCHAR(100),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Distribution
    sent_to_agent BOOLEAN DEFAULT FALSE,
    sent_to_agent_at TIMESTAMP
);

CREATE TABLE communications (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,

    -- Communication Details
    communication_type VARCHAR(50) NOT NULL,
    -- Types: phone_call, email, text, meeting
    contact_party VARCHAR(100) NOT NULL,
    -- Party: agent, lender, title_company, hoa, inspector, buyer, seller
    contact_name VARCHAR(255),

    -- Content
    summary TEXT NOT NULL,
    outcome TEXT,

    -- Follow-up
    follow_up_needed BOOLEAN DEFAULT FALSE,
    follow_up_date DATE,

    -- Tracking
    logged_by VARCHAR(100) DEFAULT 'margaret',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_classification_corrections (
    id SERIAL PRIMARY KEY,
    document_id INT REFERENCES documents(id) ON DELETE SET NULL,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    original_document_type VARCHAR(100) NOT NULL,
    corrected_document_type VARCHAR(100) NOT NULL,
    first_page_signature VARCHAR(64),
    first_page_excerpt TEXT,
    correction_reason TEXT,
    corrected_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE voice_notes (
    id SERIAL PRIMARY KEY,
    call_sid VARCHAR(80),
    recording_sid VARCHAR(80) UNIQUE,
    from_phone VARCHAR(25),
    recording_url TEXT,
    recording_duration_seconds INT DEFAULT 0,
    transcription_text TEXT,
    transcription_source VARCHAR(20),
    parse_payload JSONB DEFAULT '{}'::jsonb,
    confidence_score INT,
    note_type VARCHAR(80),
    transaction_id INT REFERENCES transactions(id) ON DELETE SET NULL,
    communication_id INT REFERENCES communications(id) ON DELETE SET NULL,
    actions_taken JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(30) DEFAULT 'received',
    review_required BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP
);

CREATE TABLE referrals (
    id SERIAL PRIMARY KEY,

    -- Referrer Info
    referrer_agent_name VARCHAR(255) NOT NULL,
    referrer_agent_phone VARCHAR(20),

    -- Referred Info
    referred_agent_name VARCHAR(255) NOT NULL,
    referred_transaction_id INT REFERENCES transactions(id),

    -- Credit
    credit_amount DECIMAL(10,2) DEFAULT 50.00,
    credit_used BOOLEAN DEFAULT FALSE,
    credit_used_on_transaction_id INT REFERENCES transactions(id),
    credit_used_date TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_access_logs (
    id SERIAL PRIMARY KEY,

    -- User Info
    user_id INT,
    user_type VARCHAR(20),
    -- Types: tc, agent, system
    user_name VARCHAR(255),

    -- Document
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,

    -- Action
    action VARCHAR(50) NOT NULL,
    -- Actions: view, download, upload, delete_attempt

    -- Tracking
    ip_address VARCHAR(50),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE predictive_alerts (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    alert_date DATE NOT NULL,
    reason TEXT NOT NULL,
    resolved_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE extracted_contract_data (
    id SERIAL PRIMARY KEY,
    transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,

    -- Source address entered by agent
    submitted_property_address TEXT,

    -- OCR extracted values
    extracted_effective_date DATE,
    extracted_closing_date DATE,
    extracted_buyer_names TEXT,
    extracted_seller_names TEXT,
    extracted_property_address TEXT,
    property_address_match BOOLEAN,
    raw_text_excerpt TEXT,

    -- Extraction status tracking
    extraction_status VARCHAR(32) DEFAULT 'pending',
    extraction_error TEXT,

    -- Margaret confirmation payload
    confirmed BOOLEAN DEFAULT FALSE,
    confirmed_effective_date DATE,
    confirmed_closing_date DATE,
    confirmed_buyer_names TEXT,
    confirmed_seller_names TEXT,
    confirmed_property_address TEXT,
    confirmed_at TIMESTAMP,
    confirmed_by VARCHAR(100),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE commission_tracking (
    id SERIAL PRIMARY KEY,
    transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    upfront_fee DECIMAL(10,2) NOT NULL,
    closing_fee DECIMAL(10,2) NOT NULL,
    referral_credit_given DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_revenue DECIMAL(10,2) NOT NULL,
    upfront_paid_date TIMESTAMP,
    closing_paid_date TIMESTAMP,
    month VARCHAR(7) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_requests (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    document_type VARCHAR(100) NOT NULL,
    requested_from VARCHAR(20) NOT NULL,
    email_sent_date TIMESTAMP,
    reminder_sent_date TIMESTAMP,
    received_date TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE client_access (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    client_type VARCHAR(20) NOT NULL,
    access_token UUID UNIQUE NOT NULL,
    email VARCHAR(255),
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP
);

CREATE TABLE contract_extractions (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    field_name VARCHAR(50) NOT NULL,
    extracted_value TEXT,
    confidence VARCHAR(10),
    agreement VARCHAR(10),
    method1_value TEXT,
    method2_value TEXT,
    method3_value TEXT,
    manually_verified BOOLEAN DEFAULT FALSE,
    verified_value TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE document_analysis_results (
    id SERIAL PRIMARY KEY,
    document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    document_type VARCHAR(50),
    analysis_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    findings JSONB,
    action_items JSONB,
    margaret_reviewed BOOLEAN DEFAULT FALSE,
    reviewed_at TIMESTAMP,
    notes TEXT
);

CREATE TABLE timeline_packets (
    id SERIAL PRIMARY KEY,
    transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    timeline_s3_key VARCHAR(500),
    timeline_filename VARCHAR(255),
    timeline_signature VARCHAR(128),
    timeline_snapshot JSONB,
    sent_recipients JSONB,
    last_trigger VARCHAR(64),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vendor_contacts (
    id SERIAL PRIMARY KEY,
    vendor_type VARCHAR(50),
    -- Types: inspector, appraiser, surveyor, title
    company_name VARCHAR(200),
    contact_name VARCHAR(200),
    email VARCHAR(200),
    phone VARCHAR(20),
    scheduling_url TEXT,
    service_area VARCHAR(150),
    preferred BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vendor_outreach (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    vendor_type VARCHAR(30) NOT NULL,
    vendor_name VARCHAR(255),
    vendor_email VARCHAR(255) NOT NULL,
    outreach_token UUID UNIQUE NOT NULL,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    response_status VARCHAR(30),
    appointment_at TIMESTAMP,
    appointment_notes TEXT,
    related_task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
    followup_task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
    last_message_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vendor_outreach_log (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    vendor_type VARCHAR(50),
    vendor_id INT REFERENCES vendor_contacts(id) ON DELETE SET NULL,
    outreach_type VARCHAR(50),
    -- Types: email_sent, follow_up_sent, response_received, scheduled
    outreach_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_received BOOLEAN DEFAULT FALSE,
    response_date TIMESTAMP,
    scheduled_date DATE,
    notes TEXT
);

CREATE TABLE calendar_events (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    vendor_outreach_id INT REFERENCES vendor_outreach(id) ON DELETE SET NULL,
    event_type VARCHAR(50),
    title VARCHAR(255) NOT NULL,
    starts_at TIMESTAMP,
    ends_at TIMESTAMP,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inbound_email_messages (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    mailbox_role VARCHAR(20) NOT NULL,
    mailbox_address VARCHAR(255) NOT NULL,
    sender_email VARCHAR(255) NOT NULL,
    sender_role VARCHAR(50) NOT NULL,
    subject TEXT,
    body_text TEXT,
    urgency VARCHAR(20),
    category VARCHAR(50),
    action_required BOOLEAN DEFAULT FALSE,
    sensitive_content BOOLEAN DEFAULT FALSE,
    at_risk BOOLEAN DEFAULT FALSE,
    recommended_route VARCHAR(30),
    applied_route VARCHAR(30),
    forwarded_to JSONB,
    sms_sent BOOLEAN DEFAULT FALSE,
    task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
    status_notes TEXT,
    provider_message_id VARCHAR(255),
    provider_payload JSONB,
    override_route VARCHAR(30),
    override_notes TEXT,
    override_by VARCHAR(100),
    override_at TIMESTAMP,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE inbound_email_rules (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    sender_role VARCHAR(50) NOT NULL,
    always_notify_margaret BOOLEAN DEFAULT FALSE,
    forward_policy VARCHAR(20) DEFAULT 'default',
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transaction_risk_flags (
    id SERIAL PRIMARY KEY,
    transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    is_at_risk BOOLEAN DEFAULT TRUE,
    reason TEXT,
    latest_message_id INT REFERENCES inbound_email_messages(id) ON DELETE SET NULL,
    flagged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE deadline_nudges (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    deadline_id INT REFERENCES deadlines(id) ON DELETE CASCADE,
    task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
    nudge_key VARCHAR(80) NOT NULL,
    deadline_type VARCHAR(80),
    due_date DATE,
    target_party VARCHAR(30) NOT NULL,
    target_email VARCHAR(255),
    target_phone VARCHAR(25),
    message_text TEXT,
    first_nudge_sent_at TIMESTAMP,
    second_nudge_sent_at TIMESTAMP,
    response_received_at TIMESTAMP,
    response_channel VARCHAR(20),
    response_text TEXT,
    requested_margaret_help BOOLEAN DEFAULT FALSE,
    escalated_at TIMESTAMP,
    escalation_task_id INT REFERENCES tasks(id) ON DELETE SET NULL,
    status VARCHAR(20) DEFAULT 'pending',
    status_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE nudge_log (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    deadline_id INT REFERENCES deadlines(id) ON DELETE CASCADE,
    nudge_type VARCHAR(100) NOT NULL,
    sent_to VARCHAR(200),
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_received BOOLEAN DEFAULT FALSE,
    response_date TIMESTAMP,
    escalated_to_margaret BOOLEAN DEFAULT FALSE
);

CREATE TABLE nudge_settings (
    id SERIAL PRIMARY KEY,
    nudge_type VARCHAR(100) UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    lead_days INT NOT NULL DEFAULT 5,
    sms_template VARCHAR(200),
    email_template VARCHAR(200),
    custom_sms_message TEXT,
    custom_email_message TEXT,
    include_preferred_vendors BOOLEAN DEFAULT TRUE,
    preferred_vendor_ids JSONB DEFAULT '[]'::jsonb,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE nudge_agent_whitelist (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(200),
    agent_phone VARCHAR(25),
    agent_email VARCHAR(200),
    notes TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE heads_up_signals (
    id SERIAL PRIMARY KEY,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    pattern_key VARCHAR(80) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    headline TEXT NOT NULL,
    suggestion TEXT NOT NULL,
    details JSONB,
    signal_date DATE NOT NULL,
    status VARCHAR(20) DEFAULT 'open',
    modified_suggestion TEXT,
    accepted_by VARCHAR(100),
    accepted_at TIMESTAMP,
    dismissed_by VARCHAR(100),
    dismissed_at TIMESTAMP,
    dismissal_notes TEXT,
    auto_action_result TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE heads_up_preferences (
    id SERIAL PRIMARY KEY,
    pattern_key VARCHAR(80) UNIQUE NOT NULL,
    always_alert BOOLEAN DEFAULT TRUE,
    auto_handle BOOLEAN DEFAULT FALSE,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE problem_detection_settings (
    id SERIAL PRIMARY KEY,
    sensitivity_level VARCHAR(20) DEFAULT 'standard',
    notification_mode VARCHAR(20) DEFAULT 'urgent_only',
    ai_enabled BOOLEAN DEFAULT TRUE,
    auto_execute_actions JSONB DEFAULT '[]'::jsonb,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE problem_detection_whitelist (
    id SERIAL PRIMARY KEY,
    transaction_id INT UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    reason TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE problem_detection_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    sensitivity_level VARCHAR(20),
    notification_mode VARCHAR(20),
    ai_enabled BOOLEAN DEFAULT TRUE,
    auto_execute_actions JSONB DEFAULT '[]'::jsonb,
    healthy_count INT DEFAULT 0,
    watch_count INT DEFAULT 0,
    urgent_count INT DEFAULT 0,
    sms_sid VARCHAR(120),
    email_message_id VARCHAR(255),
    notes TEXT
);

CREATE TABLE problem_detection_results (
    id SERIAL PRIMARY KEY,
    run_id INT REFERENCES problem_detection_runs(id) ON DELETE CASCADE,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    health_score INT NOT NULL,
    bucket VARCHAR(20) NOT NULL,
    issues JSONB DEFAULT '[]'::jsonb,
    suggestions JSONB DEFAULT '[]'::jsonb,
    auto_actions JSONB DEFAULT '[]'::jsonb,
    status VARCHAR(20) DEFAULT 'open',
    handled_by VARCHAR(100),
    handled_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bulk_messages_log (
    id SERIAL PRIMARY KEY,
    template_used VARCHAR(255),
    message_template TEXT,
    filter_scope VARCHAR(50),
    filter_status VARCHAR(50),
    party_type VARCHAR(30),
    transactions_affected INT DEFAULT 0,
    total_recipients INT DEFAULT 0,
    sent_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'queued',
    created_by VARCHAR(100),
    summary JSONB DEFAULT '{}'::jsonb,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE bulk_message_recipients (
    id SERIAL PRIMARY KEY,
    bulk_message_id INT REFERENCES bulk_messages_log(id) ON DELETE CASCADE,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    party_type VARCHAR(20),
    recipient_name VARCHAR(200),
    recipient_phone VARCHAR(25),
    rendered_message TEXT,
    status VARCHAR(20) DEFAULT 'pending',
    provider_message_sid VARCHAR(120),
    error_text TEXT,
    attempted_at TIMESTAMP,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bulk_message_templates (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(120) UNIQUE NOT NULL,
    template_body TEXT NOT NULL,
    is_system BOOLEAN DEFAULT FALSE,
    active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE task_completion_rules (
    id SERIAL PRIMARY KEY,
    task_description_pattern VARCHAR(500) NOT NULL,
    completion_trigger_type VARCHAR(50) NOT NULL,
    completion_criteria JSONB DEFAULT '{}'::jsonb,
    confidence_threshold INT DEFAULT 80,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE task_auto_completion_log (
    id SERIAL PRIMARY KEY,
    task_id INT REFERENCES tasks(id) ON DELETE CASCADE,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    rule_id INT REFERENCES task_completion_rules(id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL,
    confidence INT,
    explanation TEXT,
    snapshot JSONB DEFAULT '{}'::jsonb,
    review_required BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    undone_by VARCHAR(100),
    undone_at TIMESTAMP
);

CREATE TABLE agent_status_update_settings (
    id SERIAL PRIMARY KEY,
    enabled BOOLEAN DEFAULT TRUE,
    schedule_slot VARCHAR(30) DEFAULT 'monday_8am',
    subject_template TEXT,
    body_template TEXT,
    updated_by VARCHAR(100),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_status_update_opt_out (
    id SERIAL PRIMARY KEY,
    agent_name VARCHAR(255),
    agent_email VARCHAR(255),
    agent_phone VARCHAR(25),
    reason TEXT,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_status_update_runs (
    id SERIAL PRIMARY KEY,
    run_kind VARCHAR(30) DEFAULT 'manual',
    preview_only BOOLEAN DEFAULT FALSE,
    triggered_by VARCHAR(100),
    schedule_slot VARCHAR(30),
    schedule_week_key VARCHAR(40),
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'running',
    candidate_count INT DEFAULT 0,
    sent_count INT DEFAULT 0,
    failed_count INT DEFAULT 0,
    questions_this_week INT DEFAULT 0,
    questions_previous_week INT DEFAULT 0,
    question_reduction_estimate INT DEFAULT 0,
    notes TEXT
);

CREATE TABLE agent_status_update_messages (
    id SERIAL PRIMARY KEY,
    run_id INT REFERENCES agent_status_update_runs(id) ON DELETE CASCADE,
    transaction_id INT REFERENCES transactions(id) ON DELETE CASCADE,
    agent_name VARCHAR(255),
    agent_email VARCHAR(255),
    property_address VARCHAR(255),
    health_status VARCHAR(20),
    progress_pct INT DEFAULT 0,
    days_to_closing INT,
    urgent_item_count INT DEFAULT 0,
    tasks_completed_week INT DEFAULT 0,
    documents_uploaded_week INT DEFAULT 0,
    communications_week INT DEFAULT 0,
    upcoming_deadlines_count INT DEFAULT 0,
    agent_action_items_count INT DEFAULT 0,
    subject VARCHAR(255),
    rendered_body TEXT,
    status VARCHAR(20) DEFAULT 'preview',
    failure_reason TEXT,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- INDEXES for performance:
CREATE INDEX idx_transactions_status ON transactions(status);
CREATE INDEX idx_transactions_agent_phone ON transactions(agent_phone);
CREATE INDEX idx_transactions_closing_date ON transactions(closing_date);
CREATE INDEX idx_deadlines_transaction ON deadlines(transaction_id);
CREATE INDEX idx_deadlines_date ON deadlines(deadline_date);
CREATE INDEX idx_deadlines_type ON deadlines(deadline_type);
CREATE INDEX idx_tasks_transaction ON tasks(transaction_id);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);
CREATE INDEX idx_documents_transaction ON documents(transaction_id);
CREATE INDEX idx_documents_type ON documents(document_type);
CREATE INDEX idx_communications_transaction ON communications(transaction_id);
CREATE INDEX idx_doc_classification_corrections_doc ON document_classification_corrections(document_id, created_at DESC);
CREATE INDEX idx_doc_classification_corrections_type_map ON document_classification_corrections(original_document_type, corrected_document_type, created_at DESC);
CREATE INDEX idx_doc_classification_corrections_txn ON document_classification_corrections(transaction_id, created_at DESC);
CREATE INDEX idx_voice_notes_recording_sid ON voice_notes(recording_sid);
CREATE INDEX idx_voice_notes_transaction ON voice_notes(transaction_id, created_at DESC);
CREATE INDEX idx_voice_notes_status ON voice_notes(status, created_at DESC);
CREATE INDEX idx_voice_notes_comm ON voice_notes(communication_id);
CREATE INDEX idx_access_logs_document ON document_access_logs(document_id);
CREATE INDEX idx_access_logs_timestamp ON document_access_logs(timestamp);
CREATE UNIQUE INDEX idx_predictive_alerts_txn_alert_date ON predictive_alerts(transaction_id, alert_date);
CREATE INDEX idx_predictive_alerts_open ON predictive_alerts(transaction_id, resolved_date);
CREATE UNIQUE INDEX idx_extracted_contract_data_transaction ON extracted_contract_data(transaction_id);
CREATE UNIQUE INDEX idx_commission_tracking_transaction ON commission_tracking(transaction_id);
CREATE INDEX idx_commission_tracking_month ON commission_tracking(month);
CREATE UNIQUE INDEX idx_document_requests_txn_doc_type ON document_requests(transaction_id, document_type);
CREATE INDEX idx_document_requests_status ON document_requests(status);
CREATE UNIQUE INDEX idx_client_access_transaction_type ON client_access(transaction_id, client_type);
CREATE UNIQUE INDEX idx_client_access_token ON client_access(access_token);
CREATE UNIQUE INDEX idx_contract_extractions_txn_field ON contract_extractions(transaction_id, field_name);
CREATE INDEX idx_document_analysis_transaction ON document_analysis_results(transaction_id, analysis_date DESC);
CREATE INDEX idx_document_analysis_document ON document_analysis_results(document_id);
CREATE UNIQUE INDEX idx_timeline_packets_transaction ON timeline_packets(transaction_id);
CREATE INDEX idx_vendor_contacts_type_active ON vendor_contacts(vendor_type, active, preferred);
CREATE INDEX idx_vendor_contacts_company_name ON vendor_contacts(company_name);
CREATE INDEX idx_vendor_outreach_transaction ON vendor_outreach(transaction_id, vendor_type, sent_at DESC);
CREATE UNIQUE INDEX idx_vendor_outreach_token ON vendor_outreach(outreach_token);
CREATE INDEX idx_vendor_outreach_log_pending ON vendor_outreach_log(outreach_type, response_received, outreach_date);
CREATE INDEX idx_vendor_outreach_log_transaction ON vendor_outreach_log(transaction_id, outreach_date DESC);
CREATE INDEX idx_calendar_events_transaction ON calendar_events(transaction_id, starts_at DESC);
CREATE INDEX idx_inbound_email_messages_transaction ON inbound_email_messages(transaction_id, received_at DESC);
CREATE UNIQUE INDEX idx_inbound_email_rules_txn_role ON inbound_email_rules(transaction_id, sender_role);
CREATE UNIQUE INDEX idx_transaction_risk_flags_txn ON transaction_risk_flags(transaction_id);
CREATE INDEX idx_deadline_nudges_transaction ON deadline_nudges(transaction_id, due_date DESC);
CREATE INDEX idx_deadline_nudges_phone ON deadline_nudges(target_phone, status, response_received_at);
CREATE UNIQUE INDEX idx_deadline_nudges_unique_cycle ON deadline_nudges(transaction_id, nudge_key, due_date, target_party);
CREATE UNIQUE INDEX idx_nudge_log_unique_deadline_type ON nudge_log(transaction_id, deadline_id, nudge_type);
CREATE INDEX idx_nudge_log_sent_to ON nudge_log(sent_to, sent_at DESC);
CREATE INDEX idx_nudge_log_response ON nudge_log(nudge_type, response_received, sent_at DESC);
CREATE UNIQUE INDEX idx_nudge_settings_type ON nudge_settings(nudge_type);
CREATE UNIQUE INDEX idx_nudge_agent_whitelist_phone ON nudge_agent_whitelist(agent_phone);
CREATE UNIQUE INDEX idx_nudge_agent_whitelist_email ON nudge_agent_whitelist(agent_email);
CREATE UNIQUE INDEX idx_heads_up_signals_unique_daily ON heads_up_signals(transaction_id, pattern_key, signal_date);
CREATE INDEX idx_heads_up_signals_date_status ON heads_up_signals(signal_date, status, severity);
CREATE UNIQUE INDEX idx_heads_up_preferences_key ON heads_up_preferences(pattern_key);
CREATE UNIQUE INDEX idx_problem_detection_results_run_txn ON problem_detection_results(run_id, transaction_id);
CREATE INDEX idx_problem_detection_results_bucket_status ON problem_detection_results(bucket, status, created_at DESC);
CREATE INDEX idx_problem_detection_whitelist_active ON problem_detection_whitelist(active, transaction_id);
CREATE INDEX idx_problem_detection_runs_completed ON problem_detection_runs(completed_at DESC);
CREATE INDEX idx_bulk_messages_log_status ON bulk_messages_log(status, created_at DESC);
CREATE INDEX idx_bulk_messages_log_sent_at ON bulk_messages_log(sent_at DESC);
CREATE INDEX idx_bulk_message_recipients_bulk ON bulk_message_recipients(bulk_message_id, status, id);
CREATE UNIQUE INDEX idx_task_completion_rules_unique ON task_completion_rules(task_description_pattern, completion_trigger_type);
CREATE INDEX idx_task_auto_completion_log_task ON task_auto_completion_log(task_id, created_at DESC);
CREATE INDEX idx_task_auto_completion_log_action ON task_auto_completion_log(action, created_at DESC);
CREATE INDEX idx_agent_status_update_opt_out_active ON agent_status_update_opt_out(active, agent_email, agent_name);
CREATE INDEX idx_agent_status_update_runs_started ON agent_status_update_runs(started_at DESC, status);
CREATE INDEX idx_agent_status_update_runs_week_key ON agent_status_update_runs(schedule_week_key, run_kind, preview_only);
CREATE INDEX idx_agent_status_update_messages_run ON agent_status_update_messages(run_id, status, sent_at DESC);
CREATE INDEX idx_agent_status_update_messages_sent ON agent_status_update_messages(sent_at DESC, status);
