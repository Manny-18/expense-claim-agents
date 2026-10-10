# Setup, step by step

Written for a MacBook, works the same on Linux.

## 1. Get the code

```bash
git clone https://github.com/<your-username>/expense-claim-agents.git
cd expense-claim-agents
python3 --version        # needs 3.9 or newer
```

## 2. Run it with nothing installed

The agents, the tools and the policy retrieval use the Python standard library only.

```bash
python3 run_review.py --claim CLM-4015
python3 -m eval.evaluate
python3 -m eval.stress_test
python3 tests/test_tools.py
```

If all four work, the core system is running.

## 3. Front end and notebook

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

streamlit run app/streamlit_app.py       # opens on http://localhost:8501
jupyter notebook notebooks/demo.ipynb
```

## 4. Optional: a local model with Ollama

Nothing leaves the machine, and no API key is needed.

```bash
brew install ollama          # or download from ollama.com
ollama serve                 # leave this running in one terminal
ollama pull llama3.2:3b      # 3b is a better fit on an Intel Mac than 8b

LLM_PROVIDER=ollama LLM_MODEL=llama3.2:3b python3 run_review.py --claim CLM-4010
```

In the Streamlit sidebar, change the provider dropdown to `ollama` and the model name to
`llama3.2:3b`.

The rupee amounts are identical with or without a model. The model only changes the
wording of the employee message and the classification of free text lines.

## 5. Optional: a hosted model

```bash
cp .env.example .env
# edit .env, set LLM_PROVIDER=gemini and GEMINI_API_KEY=...
python3 run_review.py
```

## 6. Pushing to GitHub

```bash
git init
git add .
git commit -m "Expense Claim Adjudication Crew: domain expert agents for T&E review"
git branch -M main
git remote add origin https://github.com/<your-username>/expense-claim-agents.git
git push -u origin main
```

`.gitignore` already excludes `.env`, so no key is ever committed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: src` | Run commands from the repository root, not from inside a subfolder |
| `streamlit: command not found` | Activate the virtual environment, or `python3 -m streamlit run app/streamlit_app.py` |
| Ollama calls time out | Check `ollama serve` is running, then raise `LLM_TIMEOUT` in `.env` |
| Notebook kernel cannot import `src` | Open the notebook from the repository root, not from inside `notebooks/` |
