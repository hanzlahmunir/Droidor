# Retrieval Evaluation

Generated: 2026-08-06 09:37 UTC

Every number here is produced by `rag eval`, over 414 chunks and the
question set in `data/eval_questions.json`. Re-run it to regenerate.

## What is measured

Two rates, and both are needed. Either one alone is trivially maximised by
breaking the other: a floor of -1 gives perfect recall while answering
everything wrongly, and a floor of 1.0 refuses everything for a perfect
refusal rate. The floor trades one against the other.

- **recall** -- of questions the corpus CAN answer, how often the expected
  article is retrieved.
- **refusal rate** -- of questions it CANNOT answer, how often the similarity
  floor correctly refuses before any LLM call.
- **false-answer rate** -- the complement of refusal: how often it would
  answer something it should not.

This sweep measures RETRIEVAL only. The prompt is a second refusal layer that
catches what the floor lets through; it is not included here because sweeping
a dozen thresholds through an LLM would cost hundreds of calls and make the
numbers depend on sampling.

## The sweep

```
  floor   recall   refusal   false-answer   balanced
  -----   ------   -------   ------------   --------
  0.200   100.0%      0.0%         100.0%      50.0%
  0.225   100.0%      0.0%         100.0%      50.0%
  0.250   100.0%     62.5%          37.5%      81.2%
  0.275   100.0%     62.5%          37.5%      81.2%
  0.300   100.0%     62.5%          37.5%      81.2%
  0.325   100.0%     75.0%          25.0%      87.5%
  0.350   100.0%     75.0%          25.0%      87.5%
  0.375   100.0%     87.5%          12.5%      93.8% <-- best balanced
  0.400   100.0%     87.5%          12.5%      93.8%
  0.425   100.0%     87.5%          12.5%      93.8%
  0.450    86.7%     87.5%          12.5%      87.1%
  0.475    86.7%     87.5%          12.5%      87.1%
  0.500    86.7%     87.5%          12.5%      87.1%
  0.525    86.7%     87.5%          12.5%      87.1%
  0.550    86.7%    100.0%           0.0%      93.3%
  0.575    73.3%    100.0%           0.0%      86.7%
  0.600    73.3%    100.0%           0.0%      86.7%
  0.625    60.0%    100.0%           0.0%      80.0%
  0.650    53.3%    100.0%           0.0%      76.7%
```

## At the configured floor (0.400)

| Metric | Value |
| --- | ---: |
| Recall | 100.0% |
| Refusal rate | 87.5% |
| False-answer rate | 12.5% |
| Answerable questions | 15 |
| Unanswerable questions | 8 |

## What it gets wrong

```
  Unanswerable questions NOT refused by the floor
  (these reach the LLM, where the prompt is the second layer):
    ANSWERED (best 0.543): How much does Cloudflare charge per million Workers requests?
        would cite: Announcing Cloudflare Wallets: The programmable wallet for t
```

## Settings these numbers were measured under

| Setting | Value |
| --- | --- |
| `chunk_size` | 700 |
| `chunk_overlap` | 150 |
| `min_chunk_chars` | 80 |
| `embedding_model` | sentence-transformers/all-MiniLM-L6-v2 |
| `top_k` | 5 |
| `similarity_floor` | 0.4 |
| `max_context_chars` | 8000 |
| `answer_model` | openai/gpt-oss-120b |
