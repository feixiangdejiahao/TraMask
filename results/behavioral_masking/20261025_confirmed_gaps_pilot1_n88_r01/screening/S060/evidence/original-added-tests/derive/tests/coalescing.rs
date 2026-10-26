// pest. The Elegant Parser
// Licensed under MIT/Apache-2.0

extern crate pest;
#[macro_use]
extern crate pest_derive;

use pest::Parser;

#[derive(Parser)]
#[grammar = "tests/coalescing.pest"]
struct CoalescingParser;

#[test]
fn full_range() {
    assert!(CoalescingParser::parse(Rule::full_range, "a").is_ok());
    assert!(CoalescingParser::parse(Rule::full_range, "c").is_ok());
    assert!(CoalescingParser::parse(Rule::full_range, "d").is_err());
}

#[test]
fn charclass() {
    assert!(CoalescingParser::parse(Rule::charclass, "a").is_ok());
    assert!(CoalescingParser::parse(Rule::charclass, "y").is_ok());
    assert!(CoalescingParser::parse(Rule::charclass, "m").is_err());
}

#[test]
fn partial() {
    assert!(CoalescingParser::parse(Rule::partial, "a").is_ok());
    assert!(CoalescingParser::parse(Rule::partial, "c").is_ok());
    assert!(CoalescingParser::parse(Rule::partial, "foo").is_ok());
    assert!(CoalescingParser::parse(Rule::partial, "e").is_err());
}

#[test]
fn negated() {
    assert!(CoalescingParser::parse(Rule::negated, "z").is_ok());
    assert!(CoalescingParser::parse(Rule::negated, "a").is_err());
}
