# Benchmark Results

## Overall

Models ranked by average score across all attempted days.

|   Rank | Model                                                          |   Days | Part 1   | Part 2   | Score   | Avg Duration   |
|--------|----------------------------------------------------------------|--------|----------|----------|---------|----------------|
|      1 | anthropic/claude-opus-4.5                                      |     50 | 50/50    | 50/50    | 100.0%  | 46.9s          |
|      1 | anthropic/claude-sonnet-4.5                                    |     50 | 50/50    | 50/50    | 100.0%  | 60.3s          |
|      1 | claude-opus-4.6                                                |     50 | 50/50    | 50/50    | 100.0%  | 25.8s          |
|      1 | claude-sonnet-4.6                                              |     50 | 50/50    | 50/50    | 100.0%  | 26.9s          |
|      1 | gemini-3.1-pro-preview                                         |     50 | 50/50    | 50/50    | 100.0%  | 30.9s          |
|      1 | google/gemini-3-pro-preview                                    |     50 | 50/50    | 50/50    | 100.0%  | 88.2s          |
|      1 | gpt-5.4                                                        |     50 | 50/50    | 50/50    | 100.0%  | 13.8s          |
|      2 | google/gemini-3-flash-preview                                  |     50 | 50/50    | 49/50    | 99.0%   | 16.8s          |
|      2 | openai/gpt-5.2-codex                                           |     50 | 50/50    | 49/50    | 99.0%   | 49.8s          |
|      3 | moonshotai/kimi-k2.5 (no-tool-choice)                          |     50 | 49/50    | 49/50    | 98.0%   | 247.3s         |
|      4 | claude-haiku-4.5                                               |     50 | 49/50    | 48/50    | 97.0%   | 67.5s          |
|      4 | z-ai/glm-5 (prompted)                                          |     50 | 48/50    | 49/50    | 97.0%   | 156.7s         |
|      5 | z-ai/glm-4.7 (no-tool-choice)                                  |     50 | 48/50    | 47/50    | 95.0%   | 160.6s         |
|      6 | x-ai/grok-4.1-fast                                             |     50 | 50/50    | 41/50    | 91.0%   | 211.4s         |
|      7 | openai/gpt-5.1-codex-mini                                      |     50 | 48/50    | 42/50    | 90.0%   | 134.5s         |
|      8 | gpt-5.4-mini                                                   |     50 | 48/50    | 41/50    | 89.0%   | 10.7s          |
|      8 | mistralai/mistral-large-2512                                   |     50 | 48/50    | 41/50    | 89.0%   | 31.4s          |
|      8 | xiaomi/mimo-v2-flash:free (no-tool-choice)                     |     50 | 46/50    | 43/50    | 89.0%   | 206.1s         |
|      9 | moonshotai/kimi-k2-thinking (prompted)                         |     50 | 44/50    | 43/50    | 87.0%   | 188.4s         |
|     10 | x-ai/grok-code-fast-1                                          |     50 | 47/50    | 38/50    | 85.0%   | 127.8s         |
|     11 | minimax/minimax-m2.1                                           |     50 | 41/50    | 40/50    | 81.0%   | 184.6s         |
|     12 | mistralai/devstral-2512:free                                   |     50 | 28/50    | 28/50    | 56.0%   | 127.9s         |
|     13 | nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           |     50 | 19/50    | 17/50    | 36.0%   | 74.7s          |
|     14 | deepseek/deepseek-v3.2                                         |      3 | 1/3      | 1/3      | 33.3%   | 11.0s          |
|     15 | nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) |     50 | 15/50    | 17/50    | 32.0%   | 98.9s          |
|     16 | bytedance-seed/seed-1.6-flash                                  |     50 | 13/50    | 15/50    | 28.0%   | 49.1s          |
|     17 | openai/gpt-oss-120b:exacto (prompted)                          |      4 | 1/4      | 1/4      | 25.0%   | 14.0s          |
|     18 | kwaipilot/kat-coder-pro:free                                   |     50 | 9/50     | 7/50     | 16.0%   | 170.3s         |
|     19 | openai/gpt-oss-120b:exacto                                     |      6 | 0/6      | 0/6      | 0.0%    | 14.0s          |

---

## 2022

|   Rank | Model                                                          | Part 1   | Part 2   | Score   | Avg Duration   |
|--------|----------------------------------------------------------------|----------|----------|---------|----------------|
|      1 | anthropic/claude-opus-4.5                                      | 25/25    | 25/25    | 100.0%  | 52.5s          |
|      1 | anthropic/claude-sonnet-4.5                                    | 25/25    | 25/25    | 100.0%  | 70.1s          |
|      1 | claude-opus-4.6                                                | 25/25    | 25/25    | 100.0%  | 30.0s          |
|      1 | claude-sonnet-4.6                                              | 25/25    | 25/25    | 100.0%  | 28.8s          |
|      1 | gemini-3.1-pro-preview                                         | 25/25    | 25/25    | 100.0%  | 32.9s          |
|      1 | google/gemini-3-pro-preview                                    | 25/25    | 25/25    | 100.0%  | 98.1s          |
|      1 | gpt-5.4                                                        | 25/25    | 25/25    | 100.0%  | 14.0s          |
|      2 | google/gemini-3-flash-preview                                  | 25/25    | 24/25    | 98.0%   | 17.3s          |
|      2 | openai/gpt-5.2-codex                                           | 25/25    | 24/25    | 98.0%   | 64.6s          |
|      3 | moonshotai/kimi-k2.5 (no-tool-choice)                          | 24/25    | 24/25    | 96.0%   | 303.4s         |
|      3 | openai/gpt-5.1-codex-mini                                      | 25/25    | 23/25    | 96.0%   | 65.0s          |
|      3 | z-ai/glm-5 (prompted)                                          | 24/25    | 24/25    | 96.0%   | 163.7s         |
|      4 | claude-haiku-4.5                                               | 24/25    | 23/25    | 94.0%   | 87.7s          |
|      4 | z-ai/glm-4.7 (no-tool-choice)                                  | 24/25    | 23/25    | 94.0%   | 218.4s         |
|      5 | x-ai/grok-4.1-fast                                             | 25/25    | 21/25    | 92.0%   | 243.9s         |
|      6 | mistralai/mistral-large-2512                                   | 24/25    | 21/25    | 90.0%   | 31.4s          |
|      7 | gpt-5.4-mini                                                   | 24/25    | 20/25    | 88.0%   | 9.5s           |
|      7 | xiaomi/mimo-v2-flash:free (no-tool-choice)                     | 23/25    | 21/25    | 88.0%   | 254.2s         |
|      8 | x-ai/grok-code-fast-1                                          | 23/25    | 20/25    | 86.0%   | 173.8s         |
|      9 | minimax/minimax-m2.1                                           | 21/25    | 20/25    | 82.0%   | 187.9s         |
|     10 | moonshotai/kimi-k2-thinking (prompted)                         | 19/25    | 19/25    | 76.0%   | 210.5s         |
|     11 | mistralai/devstral-2512:free                                   | 15/25    | 16/25    | 62.0%   | 201.3s         |
|     12 | nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) | 10/25    | 10/25    | 40.0%   | 118.3s         |
|     13 | nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           | 10/25    | 9/25     | 38.0%   | 69.9s          |
|     14 | openai/gpt-oss-120b:exacto (prompted)                          | 1/4      | 1/4      | 25.0%   | 14.0s          |
|     15 | bytedance-seed/seed-1.6-flash                                  | 5/25     | 7/25     | 24.0%   | 52.2s          |
|     16 | kwaipilot/kat-coder-pro:free                                   | 5/25     | 5/25     | 20.0%   | 168.9s         |
|     17 | openai/gpt-oss-120b:exacto                                     | 0/6      | 0/6      | 0.0%    | 14.0s          |

---

## 2023

|   Rank | Model                                                          | Part 1   | Part 2   | Score   | Avg Duration   |
|--------|----------------------------------------------------------------|----------|----------|---------|----------------|
|      1 | anthropic/claude-opus-4.5                                      | 25/25    | 25/25    | 100.0%  | 41.2s          |
|      1 | anthropic/claude-sonnet-4.5                                    | 25/25    | 25/25    | 100.0%  | 50.6s          |
|      1 | claude-haiku-4.5                                               | 25/25    | 25/25    | 100.0%  | 47.4s          |
|      1 | claude-opus-4.6                                                | 25/25    | 25/25    | 100.0%  | 21.7s          |
|      1 | claude-sonnet-4.6                                              | 25/25    | 25/25    | 100.0%  | 25.0s          |
|      1 | gemini-3.1-pro-preview                                         | 25/25    | 25/25    | 100.0%  | 28.8s          |
|      1 | google/gemini-3-flash-preview                                  | 25/25    | 25/25    | 100.0%  | 16.3s          |
|      1 | google/gemini-3-pro-preview                                    | 25/25    | 25/25    | 100.0%  | 78.4s          |
|      1 | gpt-5.4                                                        | 25/25    | 25/25    | 100.0%  | 13.7s          |
|      1 | moonshotai/kimi-k2.5 (no-tool-choice)                          | 25/25    | 25/25    | 100.0%  | 191.2s         |
|      1 | openai/gpt-5.2-codex                                           | 25/25    | 25/25    | 100.0%  | 35.1s          |
|      2 | moonshotai/kimi-k2-thinking (prompted)                         | 25/25    | 24/25    | 98.0%   | 166.3s         |
|      2 | z-ai/glm-5 (prompted)                                          | 24/25    | 25/25    | 98.0%   | 149.7s         |
|      3 | z-ai/glm-4.7 (no-tool-choice)                                  | 24/25    | 24/25    | 96.0%   | 102.8s         |
|      4 | gpt-5.4-mini                                                   | 24/25    | 21/25    | 90.0%   | 11.9s          |
|      4 | x-ai/grok-4.1-fast                                             | 25/25    | 20/25    | 90.0%   | 179.0s         |
|      4 | xiaomi/mimo-v2-flash:free (no-tool-choice)                     | 23/25    | 22/25    | 90.0%   | 157.9s         |
|      5 | mistralai/mistral-large-2512                                   | 24/25    | 20/25    | 88.0%   | 31.3s          |
|      6 | openai/gpt-5.1-codex-mini                                      | 23/25    | 19/25    | 84.0%   | 204.0s         |
|      6 | x-ai/grok-code-fast-1                                          | 24/25    | 18/25    | 84.0%   | 81.8s          |
|      7 | minimax/minimax-m2.1                                           | 20/25    | 20/25    | 80.0%   | 181.3s         |
|      8 | mistralai/devstral-2512:free                                   | 13/25    | 12/25    | 50.0%   | 54.5s          |
|      9 | nvidia/nemotron-3-nano-30b-a3b:free (no-tool-choice)           | 9/25     | 8/25     | 34.0%   | 79.6s          |
|     10 | deepseek/deepseek-v3.2                                         | 1/3      | 1/3      | 33.3%   | 11.0s          |
|     11 | bytedance-seed/seed-1.6-flash                                  | 8/25     | 8/25     | 32.0%   | 45.9s          |
|     12 | nvidia/nemotron-3-nano-30b-a3b:free (prompted, no-tool-choice) | 5/25     | 7/25     | 24.0%   | 79.4s          |
|     13 | kwaipilot/kat-coder-pro:free                                   | 4/25     | 2/25     | 12.0%   | 171.7s         |
