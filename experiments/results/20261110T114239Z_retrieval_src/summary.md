# RAG retrieval (call-graph relevance)

Repository `src`: 1258 code chunks, 711 queries. Relevance = chunks containing the query function's repo-defined callees (AST call graph).

| Method | recall@1 | recall@3 | recall@5 | recall@10 | hit@1 | hit@3 | hit@5 | hit@10 | mrr | ndcg@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| random_baseline | 0.001 | 0.002 | 0.003 | 0.007 | 0.003 | 0.011 | 0.014 | 0.025 | 0.018 | 0.005 |
| bm25 | 0.063 | 0.180 | 0.248 | 0.362 | 0.136 | 0.328 | 0.426 | 0.571 | 0.276 | 0.244 |
| hashing | 0.092 | 0.191 | 0.264 | 0.382 | 0.174 | 0.349 | 0.452 | 0.601 | 0.308 | 0.268 |
