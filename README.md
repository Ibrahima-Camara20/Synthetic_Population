# Agents Polling
## Model 
Download **Ollama**: https://ollama.com/download

Download a model and serve it:
```console
ollama pull llama3
ollama serve
```

## Usage
Run `sim.py` in a terminal
```bash
python sim.py context.txt "Votre question ?" [--csv population_finale.csv] [--model llama3] [--output result.txt] [--limit N]
```
`context.txt` assigns values to attributes

The `limit` parameter determines how many agents the program will use(default is all of them)
