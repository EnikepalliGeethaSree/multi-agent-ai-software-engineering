# RAG retrieval (call-graph relevance)

Repository `src`: 566 code chunks, 316 queries. Relevance = chunks containing the query function's repo-defined callees (AST call graph).

| Method | recall@1 | recall@3 | recall@5 | recall@10 | hit@1 | hit@3 | hit@5 | hit@10 | mrr | ndcg@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random_baseline | 0.001 | 0.004 | 0.007 | 0.021 | 0.009 | 0.019 | 0.029 | 0.063 | 0.031 | 0.012 |
| hashing | 0.099 | 0.212 | 0.284 | 0.417 | 0.190 | 0.392 | 0.509 | 0.665 | 0.338 | 0.299 |
