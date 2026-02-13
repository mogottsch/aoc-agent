# Benchmark Results

## Overall

Models ranked by average score across all attempted days.

|   Rank | Model                                                          |   Days | Part 1   | Part 2   | Score   | Avg Tokens   | Avg Cost   | Avg Duration   |
|--------|----------------------------------------------------------------|--------|----------|----------|---------|--------------|------------|----------------|
|      1 | anthropic/claude-opus-4.5                                      |     50 | 50/50    | 50/50    | 100.0%  | 283,832      | $1.7258    | 46.9s          |
|      1 | anthropic/claude-sonnet-4.5                                    |     50 | 50/50    | 50/50    | 100.0%  | 283,832      | $1.0355    | 60.3s          |
|      1 | claude-opus-4.6                                                |     50 | 50/50    | 50/50    | 100.0%  | 52,036       | N/A        | 25.8s          |
|      1 | google/gemini-3-pro-preview                                    |     50 | 50/50    | 50/50    | 100.0%  | 162,307      | $0.4276    | 88.2s          |
|      2 | google/gemini-3-flash-preview                                  |     50 | 50/50    | 49/50    | 99.0%   | 55,475       | $0.0343    | 16.8s          |
|      2 | openai/gpt-5.2-codex                                           |     50 | 50/50    | 49/50    | 99.0%   | 278,772      | $0.6721    | 49.8s          |
|      3 | moonshotai/kimi-k2.5 (no-tool-choice)                          |     50 | 49/50    | 49/50    | 98.0%   | 297,757      | $0.1548    | 247.3s         |
|      4 | z-ai/glm-5 (prompted)                                          |     50 | 48/50    | 49/50    | 97.0%   | 277,489      | $0.2960    | 156.7s         |
|      5 | z-ai/glm-4.7 (no-tool-choice)                                  |     50 | 48/50    | 47/50    | 95.0%   | 279,190      | $0.1283    | 160.6s         |
|      6 | x-ai/grok-4.1-fast                                             |     50 | 50/50    | 41/50    | 91.0%   | 283,832      | $0.0614    | 211.4s         |
|      7 | openai/gpt-5.1-codex-mini                                      |     50 | 48/50    | 42/50    | 90.0%   | 283,832      | $0.0978    | 134.5s         |
|      8 | mistralai/mistral-large-2512                                   |     50 | 48/50    | 41/50    | 89.0%   | 283,832      | $0.1572    | 31.4s          |
|      8 | xiaomi/mimo-v2-flash:free (no-tool-choice)                     |     50 | 46/50    | 43/50    | 89.0%   | 291,741      | N/A        | 206.1s         |
|      9 | moonshotai/kimi-k2-thinking (prompted)                         |     50 | 44/50    | 43/50    | 87.0%   | 398,407      | $0.1800    | 188.4s         |
|     10 | x-ai/grok-code-fast-1                                          |     50 | 47/50    | 38/50    | 85.0%   | 156,751      | $0.0475    | 127.8s         |
|     11 | minimax/minimax-m2.1                                           |     50 | 41/50    | 40/50    | 81.0%   | 283,832      | $0.0871    | 184.6s         |
|     12 | mistralai/devstral-2512:free                                   |     50 | 28/50    | 28/50    | 56.0%   | 177,246      | N/A        | 127.9s         |
|     13 | nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           |     50 | 19/50    | 17/50    | 36.0%   | 200,648      | $0.0000    | 74.7s          |
|     14 | deepseek/deepseek-v3.2                                         |      3 | 1/3      | 1/3      | 33.3%   | 283,832      | $0.0730    | 11.0s          |
|     15 | nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) |     50 | 15/50    | 17/50    | 32.0%   | 287,816      | $0.0000    | 98.9s          |
|     16 | bytedance-seed/seed-1.6-flash                                  |     50 | 13/50    | 15/50    | 28.0%   | 283,832      | $0.0247    | 49.1s          |
|     17 | openai/gpt-oss-120b:exacto (prompted)                          |      4 | 1/4      | 1/4      | 25.0%   | 30,130       | $0.0014    | 14.0s          |
|     18 | kwaipilot/kat-coder-pro:free                                   |     50 | 9/50     | 7/50     | 16.0%   | 159,763      | N/A        | 170.3s         |
|     19 | openai/gpt-oss-120b:exacto                                     |      6 | 0/6      | 0/6      | 0.0%    | 39,012       | $0.0017    | 14.0s          |


## Cost Summary

Total cost per model and overall cost across all models.

| Model                                                          | Days     | Total Cost    |
|----------------------------------------------------------------|----------|---------------|
| anthropic/claude-opus-4.5                                      | 50       | $86.2910      |
| anthropic/claude-sonnet-4.5                                    | 50       | $51.7746      |
| openai/gpt-5.2-codex                                           | 50       | $33.6062      |
| google/gemini-3-pro-preview                                    | 50       | $21.3808      |
| z-ai/glm-5 (prompted)                                          | 50       | $14.7990      |
| moonshotai/kimi-k2-thinking (prompted)                         | 50       | $8.9977       |
| mistralai/mistral-large-2512                                   | 50       | $7.8625       |
| moonshotai/kimi-k2.5 (no-tool-choice)                          | 50       | $7.7377       |
| z-ai/glm-4.7 (no-tool-choice)                                  | 50       | $6.4130       |
| openai/gpt-5.1-codex-mini                                      | 50       | $4.8895       |
| minimax/minimax-m2.1                                           | 50       | $4.3531       |
| x-ai/grok-4.1-fast                                             | 50       | $3.0683       |
| x-ai/grok-code-fast-1                                          | 50       | $2.3752       |
| google/gemini-3-flash-preview                                  | 50       | $1.7133       |
| bytedance-seed/seed-1.6-flash                                  | 50       | $1.2369       |
| deepseek/deepseek-v3.2                                         | 3        | $0.2189       |
| openai/gpt-oss-120b:exacto                                     | 6        | $0.0103       |
| openai/gpt-oss-120b:exacto (prompted)                          | 4        | $0.0055       |
| claude-opus-4.6                                                | 50       | N/A           |
| xiaomi/mimo-v2-flash:free (no-tool-choice)                     | 50       | N/A           |
| mistralai/devstral-2512:free                                   | 50       | N/A           |
| nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           | 50       | $0.0000       |
| nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) | 50       | $0.0000       |
| kwaipilot/kat-coder-pro:free                                   | 50       | N/A           |
| **Total**                                                      | **1063** | **$256.7333** |

---

## 2022

|   Rank | Model                                                          | Part 1   | Part 2   | Score   | Avg Tokens   | Avg Cost   | Avg Duration   |
|--------|----------------------------------------------------------------|----------|----------|---------|--------------|------------|----------------|
|      1 | anthropic/claude-opus-4.5                                      | 25/25    | 25/25    | 100.0%  | 283,832      | $1.7258    | 52.5s          |
|      1 | anthropic/claude-sonnet-4.5                                    | 25/25    | 25/25    | 100.0%  | 283,832      | $1.0355    | 70.1s          |
|      1 | claude-opus-4.6                                                | 25/25    | 25/25    | 100.0%  | 50,331       | N/A        | 30.0s          |
|      1 | google/gemini-3-pro-preview                                    | 25/25    | 25/25    | 100.0%  | 283,832      | $0.7210    | 98.1s          |
|      2 | google/gemini-3-flash-preview                                  | 25/25    | 24/25    | 98.0%   | 59,376       | $0.0363    | 17.3s          |
|      2 | openai/gpt-5.2-codex                                           | 25/25    | 24/25    | 98.0%   | 283,832      | $0.6845    | 64.6s          |
|      3 | moonshotai/kimi-k2.5 (no-tool-choice)                          | 24/25    | 24/25    | 96.0%   | 383,975      | $0.1976    | 303.4s         |
|      3 | openai/gpt-5.1-codex-mini                                      | 25/25    | 23/25    | 96.0%   | 283,832      | $0.0978    | 65.0s          |
|      3 | z-ai/glm-5 (prompted)                                          | 24/25    | 24/25    | 96.0%   | 290,741      | $0.3104    | 163.7s         |
|      4 | z-ai/glm-4.7 (no-tool-choice)                                  | 24/25    | 23/25    | 94.0%   | 283,832      | $0.1304    | 218.4s         |
|      5 | x-ai/grok-4.1-fast                                             | 25/25    | 21/25    | 92.0%   | 283,832      | $0.0614    | 243.9s         |
|      6 | mistralai/mistral-large-2512                                   | 24/25    | 21/25    | 90.0%   | 283,832      | $0.1572    | 31.4s          |
|      7 | xiaomi/mimo-v2-flash:free (no-tool-choice)                     | 23/25    | 21/25    | 88.0%   | 283,832      | N/A        | 254.2s         |
|      8 | x-ai/grok-code-fast-1                                          | 23/25    | 20/25    | 86.0%   | 283,832      | $0.0767    | 173.8s         |
|      9 | minimax/minimax-m2.1                                           | 21/25    | 20/25    | 82.0%   | 283,832      | $0.0871    | 187.9s         |
|     10 | moonshotai/kimi-k2-thinking (prompted)                         | 19/25    | 19/25    | 76.0%   | 521,153      | $0.2321    | 210.5s         |
|     11 | mistralai/devstral-2512:free                                   | 15/25    | 16/25    | 62.0%   | 283,832      | N/A        | 201.3s         |
|     12 | nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) | 10/25    | 10/25    | 40.0%   | 302,694      | $0.0000    | 118.3s         |
|     13 | nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           | 10/25    | 9/25     | 38.0%   | 283,832      | $0.0000    | 69.9s          |
|     14 | openai/gpt-oss-120b:exacto (prompted)                          | 1/4      | 1/4      | 25.0%   | 30,130       | $0.0014    | 14.0s          |
|     15 | bytedance-seed/seed-1.6-flash                                  | 5/25     | 7/25     | 24.0%   | 283,832      | $0.0247    | 52.2s          |
|     16 | kwaipilot/kat-coder-pro:free                                   | 5/25     | 5/25     | 20.0%   | 283,832      | N/A        | 168.9s         |
|     17 | openai/gpt-oss-120b:exacto                                     | 0/6      | 0/6      | 0.0%    | 39,012       | $0.0017    | 14.0s          |

---

## 2023

|   Rank | Model                                                          | Part 1   | Part 2   | Score   | Avg Tokens   | Avg Cost   | Avg Duration   |
|--------|----------------------------------------------------------------|----------|----------|---------|--------------|------------|----------------|
|      1 | anthropic/claude-opus-4.5                                      | 25/25    | 25/25    | 100.0%  | 283,832      | $1.7258    | 41.2s          |
|      1 | anthropic/claude-sonnet-4.5                                    | 25/25    | 25/25    | 100.0%  | 283,832      | $1.0355    | 50.6s          |
|      1 | claude-opus-4.6                                                | 25/25    | 25/25    | 100.0%  | 53,742       | N/A        | 21.7s          |
|      1 | google/gemini-3-flash-preview                                  | 25/25    | 25/25    | 100.0%  | 51,573       | $0.0322    | 16.3s          |
|      1 | google/gemini-3-pro-preview                                    | 25/25    | 25/25    | 100.0%  | 40,782       | $0.1342    | 78.4s          |
|      1 | moonshotai/kimi-k2.5 (no-tool-choice)                          | 25/25    | 25/25    | 100.0%  | 211,539      | $0.1119    | 191.2s         |
|      1 | openai/gpt-5.2-codex                                           | 25/25    | 25/25    | 100.0%  | 273,712      | $0.6597    | 35.1s          |
|      2 | moonshotai/kimi-k2-thinking (prompted)                         | 25/25    | 24/25    | 98.0%   | 275,661      | $0.1278    | 166.3s         |
|      2 | z-ai/glm-5 (prompted)                                          | 24/25    | 25/25    | 98.0%   | 264,238      | $0.2815    | 149.7s         |
|      3 | z-ai/glm-4.7 (no-tool-choice)                                  | 24/25    | 24/25    | 96.0%   | 274,549      | $0.1261    | 102.8s         |
|      4 | x-ai/grok-4.1-fast                                             | 25/25    | 20/25    | 90.0%   | 283,832      | $0.0614    | 179.0s         |
|      4 | xiaomi/mimo-v2-flash:free (no-tool-choice)                     | 23/25    | 22/25    | 90.0%   | 299,650      | N/A        | 157.9s         |
|      5 | mistralai/mistral-large-2512                                   | 24/25    | 20/25    | 88.0%   | 283,832      | $0.1572    | 31.3s          |
|      6 | openai/gpt-5.1-codex-mini                                      | 23/25    | 19/25    | 84.0%   | 283,832      | $0.0978    | 204.0s         |
|      6 | x-ai/grok-code-fast-1                                          | 24/25    | 18/25    | 84.0%   | 29,671       | $0.0183    | 81.8s          |
|      7 | minimax/minimax-m2.1                                           | 20/25    | 20/25    | 80.0%   | 283,832      | $0.0871    | 181.3s         |
|      8 | mistralai/devstral-2512:free                                   | 13/25    | 12/25    | 50.0%   | 70,661       | N/A        | 54.5s          |
|      9 | nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           | 9/25     | 8/25     | 34.0%   | 117,464      | $0.0000    | 79.6s          |
|     10 | deepseek/deepseek-v3.2                                         | 1/3      | 1/3      | 33.3%   | 283,832      | $0.0730    | 11.0s          |
|     11 | bytedance-seed/seed-1.6-flash                                  | 8/25     | 8/25     | 32.0%   | 283,832      | $0.0247    | 45.9s          |
|     12 | nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) | 5/25     | 7/25     | 24.0%   | 272,938      | $0.0000    | 79.4s          |
|     13 | kwaipilot/kat-coder-pro:free                                   | 4/25     | 2/25     | 12.0%   | 35,694       | N/A        | 171.7s         |
