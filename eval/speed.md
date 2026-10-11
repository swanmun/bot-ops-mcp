# Speed, same conditions (RTX 4060 Ti 16 GB, 32 GB RAM, Ollama)

One model at a time; a ~1.5k-token prompt, 256 output tokens, median of 3 runs after a warm-up. Thinking off, temperature 0, 16k context, no memory mapping. `eval/speed_bench.py`.

| Model | On GPU | Load (s) | Prompt tok/s | Output tok/s | Output runs |
|---|---|---|---|---|---|
| gemma4:e2b | 100% | 3.8 | 7627 | **118.9** | 118.9, 121.0, 118.9 |
| gemma4:e4b | 100% | 4.3 | 4581 | **69.0** | 69.3, 69.0, 68.2 |
| gemma4:12b-it-qat | 100% | 6.2 | 2008 | **31.8** | 32.2, 31.8, 31.7 |
| gemma4:12b | 100% | 8.0 | 1733 | **76.3** | 76.3, 77.6, 76.3 |
| gemma4:12b-it-q8_0 | 100% | 9.0 | 1850 | **19.0** | 19.1, 19.0, 18.9 |
| gemma4:26b-a4b-it-qat | 84% | 16.3 | 1710 | **56.4** | 56.4, 59.1, 53.6 |
| qwen3:8b | 100% | 4.5 | 3218 | **45.9** | 45.9, 45.9, 45.8 |
| qwen3:14b | 100% | 6.2 | 1739 | **26.8** | 26.9, 26.8, 26.6 |
| qwen3.8:27b | 67% | 15.2 | 413 | **9.3** | 10.1, 9.3, 9.1 |

Notes
- Measured 2026-10-11 with the previous demo log as the prompt (same length within a few lines); the demo was
  rebuilt with the demo rules on 10-12. Output speed does not depend on what the log says.
- No memory column: Ollama's `/api/ps` reported 1.4 GB for gemma4:12b while `nvidia-smi` showed about 8 GB in use
  (10.7 GB on the card, about 2.4 GB at idle). *On GPU* is still the share `/api/ps` reports.
- gemma4:12b (Q4_K_M) at about 75 tokens/s is confirmed by wall-clock time (73.8 tok/s). Reading about 7 GB of weights
  once per token on this card (about 288 GB/s) allows a little over 40 tokens/s, so the runtime must be doing more than
  one plain forward pass per token for this tag (speculative decoding, for example). Not verified. The QAT tag (Q4_0)
  of the same model runs at about 31 tokens/s.
