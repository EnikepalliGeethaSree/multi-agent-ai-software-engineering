# RAG retrieval (call-graph relevance)

Repository `src`: 315 code chunks, 138 queries. Relevance = chunks containing the query function's repo-defined callees (AST call graph).

| Method | recall@1 | recall@3 | recall@5 | recall@10 | hit@1 | hit@3 | hit@5 | hit@10 | mrr | ndcg@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random_baseline | 0.002 | 0.006 | 0.020 | 0.031 | 0.007 | 0.022 | 0.036 | 0.058 | 0.036 | 0.016 |
| hashing | 0.116 | 0.280 | 0.404 | 0.541 | 0.239 | 0.493 | 0.681 | 0.797 | 0.412 | 0.379 |
