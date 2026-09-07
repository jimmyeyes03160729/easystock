easystock v0.60.1 hotfix

Overwrite these paths in the repository root:
- update_market.py
- requirements.txt
- .github/workflows/update.yml
- tests/test_parsers.py

After commit/push, verify:
1. update_market.py contains no "import finlab".
2. .github/workflows/update.yml contains no "pip install finlab" or FINLAB_API_TOKEN.
3. requirements.txt contains only requests, numpy, firebase-admin.
4. Run GitHub Actions -> Daily Stock Data Update -> Run workflow.
