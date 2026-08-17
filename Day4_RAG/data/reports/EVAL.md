# Retrieval Evaluation

Generated: 2026-08-17 15:10 UTC

Every number here is produced by `rag eval`, over 2183 chunks and the
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
  0.250   100.0%      0.0%         100.0%      50.0%
  0.275   100.0%      7.7%          92.3%      53.8%
  0.300   100.0%      7.7%          92.3%      53.8%
  0.325   100.0%     15.4%          84.6%      57.7%
  0.350   100.0%     23.1%          76.9%      61.5%
  0.375   100.0%     38.5%          61.5%      69.2%
  0.400   100.0%     46.2%          53.8%      73.1%
  0.425   100.0%     53.8%          46.2%      76.9%
  0.450    93.3%     53.8%          46.2%      73.6%
  0.475    90.0%     53.8%          46.2%      71.9%
  0.500    90.0%     61.5%          38.5%      75.8%
  0.525    86.7%     69.2%          30.8%      77.9%
  0.550    86.7%     69.2%          30.8%      77.9%
  0.575    73.3%     84.6%          15.4%      79.0% <-- best balanced
  0.600    70.0%     84.6%          15.4%      77.3%
  0.625    60.0%     92.3%           7.7%      76.2%
  0.650    50.0%     92.3%           7.7%      71.2%
```

## At the configured floor (0.425)

| Metric | Value |
| --- | ---: |
| Recall | 100.0% |
| Refusal rate | 53.8% |
| False-answer rate | 46.2% |
| Answerable questions | 30 |
| Unanswerable questions | 13 |

## What it gets wrong

```
  Unanswerable questions NOT refused by the floor
  (these reach the LLM, where the prompt is the second layer):
    ANSWERED (best 0.601): How much does Cloudflare charge per million Workers requests?
        would cite: Unifying Workers AI and AI Gateway into a single AI control 
    ANSWERED (best 0.498): How do I set up OAuth2 device flow authentication in Rust?
        would cite: The Agent Access Model
    ANSWERED (best 0.505): What SQLite page size does the author recommend?
        would cite: Learning a few things about running SQLite
    ANSWERED (best 0.571): What is the parameter count of the model behind SymptomAI?
        would cite: SymptomAI: Towards a conversational AI agent for everyday sy
    ANSWERED (best 0.569): Which Django version does the author recommend for production?
        would cite: Some more things about Django I've been enjoying
    ANSWERED (best 0.702): What accuracy did SymptomAI achieve on its benchmark?
        would cite: SymptomAI: Towards a conversational AI agent for everyday sy
```

## Settings these numbers were measured under

| Setting | Value |
| --- | --- |
| `chunk_size` | 700 |
| `chunk_overlap` | 150 |
| `min_chunk_chars` | 80 |
| `embedding_model` | sentence-transformers/all-MiniLM-L6-v2 |
| `top_k` | 12 |
| `similarity_floor` | 0.425 |
| `max_context_chars` | 8000 |
| `answer_model` | openai/gpt-oss-120b |
