// pest. The Elegant Parser
// Licensed under MIT/Apache-2.0

extern crate pest;
extern crate pest_meta;
extern crate pest_vm;

use pest_meta::optimizer::{OptimizedExpr, OptimizedRule};
use pest_meta::parser::Rule;
use pest_meta::{optimizer, parser};
use pest_vm::Vm;

const GRAMMAR: &str = include_str!("coalescing.pest");

fn optimized() -> Vec<OptimizedRule> {
    let pairs = parser::parse(Rule::grammar_rules, GRAMMAR).unwrap();
    let ast = parser::consume_rules(pairs).unwrap();
    optimizer::optimize(ast)
}

#[test]
fn full_range_collapses() {
    let rules = optimized();
    let rule = rules.iter().find(|r| r.name == "full_range").unwrap();
    assert_eq!(
        rule.expr,
        OptimizedExpr::Range("a".to_owned(), "c".to_owned())
    );
}

#[test]
fn char_class_is_produced() {
    let rules = optimized();
    let rule = rules.iter().find(|r| r.name == "two_ranges").unwrap();
    assert_eq!(
        rule.expr,
        OptimizedExpr::CharClass(vec![
            ("a".to_owned(), "c".to_owned()),
            ("x".to_owned(), "z".to_owned()),
        ])
    );
}

#[test]
fn partial_run_is_coalesced() {
    let rules = optimized();
    let rule = rules.iter().find(|r| r.name == "partial").unwrap();
    assert_eq!(
        rule.expr,
        OptimizedExpr::Choice(
            Box::new(OptimizedExpr::Str("a".to_owned())),
            Box::new(OptimizedExpr::Choice(
                Box::new(OptimizedExpr::Ident("ident".to_owned())),
                Box::new(OptimizedExpr::Range("b".to_owned(), "d".to_owned())),
            )),
        )
    );
}

#[test]
fn neg_char_class_is_produced() {
    let rules = optimized();
    let rule = rules.iter().find(|r| r.name == "negated").unwrap();
    assert_eq!(
        rule.expr,
        OptimizedExpr::NegCharClass(vec![("a".to_owned(), "c".to_owned())])
    );
}

#[test]
fn neg_char_class_single_is_produced() {
    let rules = optimized();
    let rule = rules.iter().find(|r| r.name == "negated_single").unwrap();
    assert_eq!(
        rule.expr,
        OptimizedExpr::NegCharClass(vec![("x".to_owned(), "x".to_owned())])
    );
}

#[test]
fn vm_parses_char_class() {
    let rules = optimized();
    let vm = Vm::new(rules);
    assert!(vm.parse("full_range", "a").is_ok());
    assert!(vm.parse("full_range", "c").is_ok());
    assert!(vm.parse("full_range", "d").is_err());

    assert!(vm.parse("two_ranges", "b").is_ok());
    assert!(vm.parse("two_ranges", "y").is_ok());
    assert!(vm.parse("two_ranges", "m").is_err());

    assert!(vm.parse("partial", "a").is_ok());
    assert!(vm.parse("partial", "c").is_ok());
    assert!(vm.parse("partial", "foo").is_ok());
    assert!(vm.parse("partial", "e").is_err());

    assert!(vm.parse("negated", "d").is_ok());
    assert!(vm.parse("negated", "a").is_err());
    assert!(vm.parse("negated_single", "a").is_ok());
    assert!(vm.parse("negated_single", "x").is_err());

    assert!(vm.parse("mixed", "A").is_ok());
    assert!(vm.parse("mixed", "a").is_ok());
    assert!(vm.parse("mixed", "d").is_ok());
    assert!(vm.parse("mixed", "e").is_err());
}
