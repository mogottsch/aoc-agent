# Benchmark Results

## Overall

Models ranked by average score across all attempted days.

|   Rank | Model                               |   Days | Part 1   | Part 2   | Score   | Avg Tokens   | Avg Cost   | Avg Duration   |
|--------|-------------------------------------|--------|----------|----------|---------|--------------|------------|----------------|
|      1 | anthropic/claude-opus-4.5           |     50 | 50/50    | 50/50    | 100.0%  | 124,641      | $0.7175    | 46.9s          |
|      1 | anthropic/claude-sonnet-4.5         |     50 | 50/50    | 50/50    | 100.0%  | 124,641      | $0.4305    | 60.3s          |
|      1 | google/gemini-3-pro-preview         |     50 | 50/50    | 50/50    | 100.0%  | 106,596      | $0.2825    | 88.2s          |
|      2 | openai/gpt-5.2-codex                |     50 | 50/50    | 49/50    | 99.0%   | 122,765      | $0.2716    | 49.8s          |
|      3 | google/gemini-3-flash-preview       |     18 | 18/18    | 17/18    | 97.2%   | 53,202       | $0.0316    | 13.9s          |
|      4 | z-ai/glm-4.7                        |     50 | 48/50    | 47/50    | 95.0%   | 124,257      | $0.0549    | 160.6s         |
|      5 | x-ai/grok-4.1-fast                  |     50 | 50/50    | 41/50    | 91.0%   | 124,641      | $0.0263    | 211.4s         |
|      6 | openai/gpt-5.1-codex-mini           |     50 | 48/50    | 42/50    | 90.0%   | 124,641      | $0.0394    | 134.5s         |
|      7 | mistralai/mistral-large-2512        |     50 | 48/50    | 41/50    | 89.0%   | 124,641      | $0.0670    | 31.4s          |
|      7 | xiaomi/mimo-v2-flash:free           |     50 | 46/50    | 43/50    | 89.0%   | 361,970      | $0.0000    | 206.1s         |
|      8 | x-ai/grok-code-fast-1               |     50 | 47/50    | 38/50    | 85.0%   | 100,592      | $0.0338    | 127.8s         |
|      9 | minimax/minimax-m2.1                |     50 | 41/50    | 40/50    | 81.0%   | 124,641      | $0.0377    | 184.6s         |
|     10 | mistralai/devstral-2512:free        |     50 | 28/50    | 28/50    | 56.0%   | 132,981      | $0.0000    | 127.9s         |
|     11 | nvidia/nemotron-3-nano-30b-a3b:free |     50 | 19/50    | 17/50    | 36.0%   | 190,022      | $0.0000    | 74.7s          |
|     12 | deepseek/deepseek-v3.2              |      3 | 1/3      | 1/3      | 33.3%   | 124,641      | $0.0318    | 11.0s          |
|     13 | moonshotai/kimi-k2-thinking         |     50 | 21/50    | 12/50    | 33.0%   | 124,641      | $0.0562    | 70.5s          |
|     14 | bytedance-seed/seed-1.6-flash       |     50 | 13/50    | 15/50    | 28.0%   | 124,641      | $0.0104    | 49.1s          |
|     15 | kwaipilot/kat-coder-pro:free        |     50 | 9/50     | 7/50     | 16.0%   | 98,015       | N/A        | 170.3s         |


## Cost Summary

Total cost per model and overall cost across all models.

| Model                               | Days    | Total Cost    |
|-------------------------------------|---------|---------------|
| anthropic/claude-opus-4.5           | 50      | $35.8752      |
| anthropic/claude-sonnet-4.5         | 50      | $21.5252      |
| google/gemini-3-pro-preview         | 50      | $14.1227      |
| openai/gpt-5.2-codex                | 50      | $13.5821      |
| mistralai/mistral-large-2512        | 50      | $3.3518       |
| moonshotai/kimi-k2-thinking         | 50      | $2.8111       |
| z-ai/glm-4.7                        | 50      | $2.7439       |
| openai/gpt-5.1-codex-mini           | 50      | $1.9706       |
| minimax/minimax-m2.1                | 50      | $1.8830       |
| x-ai/grok-code-fast-1               | 50      | $1.6919       |
| x-ai/grok-4.1-fast                  | 50      | $1.3171       |
| google/gemini-3-flash-preview       | 18      | $0.5687       |
| bytedance-seed/seed-1.6-flash       | 50      | $0.5204       |
| deepseek/deepseek-v3.2              | 3       | $0.0953       |
| xiaomi/mimo-v2-flash:free           | 50      | $0.0000       |
| mistralai/devstral-2512:free        | 50      | $0.0000       |
| nvidia/nemotron-3-nano-30b-a3b:free | 50      | $0.0000       |
| kwaipilot/kat-coder-pro:free        | 50      | N/A           |
| **Total**                           | **821** | **$102.0591** |

---

## 2022

|   Rank | Model                               | Part 1   | Part 2   | Score   | Avg Tokens   | Avg Cost   | Avg Duration   |
|--------|-------------------------------------|----------|----------|---------|--------------|------------|----------------|
|      1 | anthropic/claude-opus-4.5           | 25/25    | 25/25    | 100.0%  | 124,641      | $0.7175    | 52.5s          |
|      1 | anthropic/claude-sonnet-4.5         | 25/25    | 25/25    | 100.0%  | 124,641      | $0.4305    | 70.1s          |
|      1 | google/gemini-3-pro-preview         | 25/25    | 25/25    | 100.0%  | 124,641      | $0.2964    | 98.1s          |
|      2 | openai/gpt-5.2-codex                | 25/25    | 24/25    | 98.0%   | 124,641      | $0.2759    | 64.6s          |
|      3 | google/gemini-3-flash-preview       | 18/18    | 17/18    | 97.2%   | 53,202       | $0.0316    | 13.9s          |
|      4 | openai/gpt-5.1-codex-mini           | 25/25    | 23/25    | 96.0%   | 124,641      | $0.0394    | 65.0s          |
|      5 | z-ai/glm-4.7                        | 24/25    | 23/25    | 94.0%   | 124,641      | $0.0550    | 218.4s         |
|      6 | x-ai/grok-4.1-fast                  | 25/25    | 21/25    | 92.0%   | 124,641      | $0.0263    | 243.9s         |
|      7 | mistralai/mistral-large-2512        | 24/25    | 21/25    | 90.0%   | 124,641      | $0.0670    | 31.4s          |
|      8 | xiaomi/mimo-v2-flash:free           | 23/25    | 21/25    | 88.0%   | 124,641      | $0.0000    | 254.2s         |
|      9 | x-ai/grok-code-fast-1               | 23/25    | 20/25    | 86.0%   | 124,641      | $0.0311    | 173.8s         |
|     10 | minimax/minimax-m2.1                | 21/25    | 20/25    | 82.0%   | 124,641      | $0.0377    | 187.9s         |
|     11 | mistralai/devstral-2512:free        | 15/25    | 16/25    | 62.0%   | 124,641      | $0.0000    | 201.3s         |
|     12 | nvidia/nemotron-3-nano-30b-a3b:free | 10/25    | 9/25     | 38.0%   | 124,641      | $0.0000    | 69.9s          |
|     13 | bytedance-seed/seed-1.6-flash       | 5/25     | 7/25     | 24.0%   | 124,641      | $0.0104    | 52.2s          |
|     13 | moonshotai/kimi-k2-thinking         | 8/25     | 4/25     | 24.0%   | 124,641      | $0.0562    | 76.1s          |
|     14 | kwaipilot/kat-coder-pro:free        | 5/25     | 5/25     | 20.0%   | 124,641      | N/A        | 168.9s         |

---

## 2023

|   Rank | Model                               | Part 1   | Part 2   | Score   | Avg Tokens   | Avg Cost   | Avg Duration   |
|--------|-------------------------------------|----------|----------|---------|--------------|------------|----------------|
|      1 | anthropic/claude-opus-4.5           | 25/25    | 25/25    | 100.0%  | 124,641      | $0.7175    | 41.2s          |
|      1 | anthropic/claude-sonnet-4.5         | 25/25    | 25/25    | 100.0%  | 124,641      | $0.4305    | 50.6s          |
|      1 | google/gemini-3-pro-preview         | 25/25    | 25/25    | 100.0%  | 88,552       | $0.2685    | 78.4s          |
|      1 | openai/gpt-5.2-codex                | 25/25    | 25/25    | 100.0%  | 120,889      | $0.2674    | 35.1s          |
|      2 | z-ai/glm-4.7                        | 24/25    | 24/25    | 96.0%   | 123,874      | $0.0547    | 102.8s         |
|      3 | x-ai/grok-4.1-fast                  | 25/25    | 20/25    | 90.0%   | 124,641      | $0.0263    | 179.0s         |
|      3 | xiaomi/mimo-v2-flash:free           | 23/25    | 22/25    | 90.0%   | 599,300      | $0.0000    | 157.9s         |
|      4 | mistralai/mistral-large-2512        | 24/25    | 20/25    | 88.0%   | 124,641      | $0.0670    | 31.3s          |
|      5 | openai/gpt-5.1-codex-mini           | 23/25    | 19/25    | 84.0%   | 124,641      | $0.0394    | 204.0s         |
|      5 | x-ai/grok-code-fast-1               | 24/25    | 18/25    | 84.0%   | 76,544       | $0.0366    | 81.8s          |
|      6 | minimax/minimax-m2.1                | 20/25    | 20/25    | 80.0%   | 124,641      | $0.0377    | 181.3s         |
|      7 | mistralai/devstral-2512:free        | 13/25    | 12/25    | 50.0%   | 141,322      | $0.0000    | 54.5s          |
|      8 | moonshotai/kimi-k2-thinking         | 13/25    | 8/25     | 42.0%   | 124,641      | $0.0562    | 64.9s          |
|      9 | nvidia/nemotron-3-nano-30b-a3b:free | 9/25     | 8/25     | 34.0%   | 255,404      | $0.0000    | 79.6s          |
|     10 | deepseek/deepseek-v3.2              | 1/3      | 1/3      | 33.3%   | 124,641      | $0.0318    | 11.0s          |
|     11 | bytedance-seed/seed-1.6-flash       | 8/25     | 8/25     | 32.0%   | 124,641      | $0.0104    | 45.9s          |
|     12 | kwaipilot/kat-coder-pro:free        | 4/25     | 2/25     | 12.0%   | 71,389       | N/A        | 171.7s         |
