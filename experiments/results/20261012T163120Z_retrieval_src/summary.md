# RAG retrieval (call-graph relevance)

Repository `src`: 665 code chunks, 381 queries. Relevance = chunks containing the query function's repo-defined callees (AST call graph).

| Method | recall@1 | recall@3 | recall@5 | recall@10 | hit@1 | hit@3 | hit@5 | hit@10 | mrr | ndcg@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random_baseline | 0.001 | 0.005 | 0.005 | 0.012 | 0.003 | 0.011 | 0.013 | 0.032 | 0.020 | 0.007 |
| hashing | 0.090 | 0.188 | 0.264 | 0.365 | 0.173 | 0.360 | 0.480 | 0.606 | 0.312 | 0.266 |
