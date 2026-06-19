CREATE TABLE record_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    -- discovery | people | sources | monitoring | financials | crypto
    description TEXT
);

INSERT INTO record_types (code, category, description) VALUES
  ('github_repo',           'discovery',  'Company GitHub repo/org found'),
  ('hf_org',                'discovery',  'HuggingFace organization found'),
  ('hf_model',              'discovery',  'HuggingFace model found'),
  ('job_posting',           'discovery',  'Job posting referencing the company'),
  ('papers_with_code',      'discovery',  'PapersWithCode reference'),
  ('funding_announcement',  'financials', 'Funding/round announcement'),
  ('kaggle_sponsor',        'discovery',  'Kaggle competition sponsor'),
  ('scale_customer',        'discovery',  'Listed as customer of a known vendor'),
  ('wandb_run',             'discovery',  'Weights & Biases public run'),
  ('directory_listing',     'discovery',  'Found in a directory listing'),
  ('contact_found',         'people',     'A person/contact discovered for the company'),
  ('source_link',           'sources',    'A curated source URL for analysis'),
  ('news',                  'monitoring', 'News article about the company'),
  ('product_update',        'monitoring', 'Product/release update detected'),
  ('foundation_model',      'discovery',  'Company uses or develops a foundation model'),
  ('proprietary_ai',        'discovery',  'Company has proprietary AI capability'),
  ('proprietary_models',    'discovery',  'Company has proprietary model(s)');
