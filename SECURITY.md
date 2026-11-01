# Security and data handling
- API keys: use environment variables or Streamlit secrets; never commit them. Rotate a key if it is ever exposed.
- The web app keeps uploads in session memory only. The agent sends tool *results* (statistics, tables you ask about) to the model provider, not your rasters.
- Do not upload confidential infrastructure data without permission from its owner. Use synthetic or open data for public demos.
- Report vulnerabilities privately to the repository owner (enable GitHub private vulnerability reporting).
