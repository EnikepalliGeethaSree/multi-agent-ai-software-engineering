# RAG retrieval (call-graph relevance)

Repository `src`: 510 code chunks, 277 queries. Relevance = chunks containing the query function's repo-defined callees (AST call graph).

| Method | recall@1 | recall@3 | recall@5 | recall@10 | hit@1 | hit@3 | hit@5 | hit@10 | mrr | ndcg@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random_baseline | 0.006 | 0.008 | 0.010 | 0.030 | 0.011 | 0.022 | 0.036 | 0.076 | 0.037 | 0.018 |
| hashing | 0.099 | 0.217 | 0.294 | 0.438 | 0.202 | 0.404 | 0.527 | 0.690 | 0.354 | 0.311 |
