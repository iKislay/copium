//! ROUGE-L benchmark — measures quality gate performance across input sizes.

use copium_core::transforms::quality_gate::rouge_l::{rouge_l, rouge_l_str};
use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion};

fn generate_tokens(n: usize) -> Vec<String> {
    (0..n).map(|i| format!("token{i}")).collect()
}

fn bench_rouge_l(c: &mut Criterion) {
    let mut group = c.benchmark_group("rouge_l");

    for size in [50, 250, 500, 1000, 2500, 5000] {
        let ref_tokens = generate_tokens(size);
        // Candidate is reference with 10% tokens replaced
        let mut cand_tokens = ref_tokens.clone();
        for i in (0..size).step_by(10) {
            cand_tokens[i] = format!("replaced{i}");
        }

        let ref_slices: Vec<&str> = ref_tokens.iter().map(|s| s.as_str()).collect();
        let cand_slices: Vec<&str> = cand_tokens.iter().map(|s| s.as_str()).collect();

        group.bench_with_input(
            BenchmarkId::new("tokens", size),
            &(ref_slices, cand_slices),
            |b, (r, c)| {
                b.iter(|| rouge_l(black_box(r), black_box(c)));
            },
        );
    }
    group.finish();

    let mut str_group = c.benchmark_group("rouge_l_str");
    for size_kb in [1, 5, 10] {
        let words_per_kb = 150; // ~150 words per KB
        let word_count = size_kb * words_per_kb;
        let reference: String = (0..word_count)
            .map(|i| format!("word{i}"))
            .collect::<Vec<_>>()
            .join(" ");
        // 10% word replacement
        let candidate: String = (0..word_count)
            .map(|i| {
                if i % 10 == 0 {
                    format!("changed{i}")
                } else {
                    format!("word{i}")
                }
            })
            .collect::<Vec<_>>()
            .join(" ");

        str_group.bench_with_input(
            BenchmarkId::new("kb", size_kb),
            &(reference, candidate),
            |b, (r, c)| {
                b.iter(|| rouge_l_str(black_box(r), black_box(c)));
            },
        );
    }
    str_group.finish();
}

criterion_group!(benches, bench_rouge_l);
criterion_main!(benches);
