//! Cogit core: canonical JSON, object schemas, and the content-addressed
//! object store. Contract: docs/spec/object-format-v1.md; object identity
//! is frozen by prototype/vectors/object-vectors-v1.json (ADR-0010) and
//! this crate must reproduce those IDs byte-for-byte.

pub mod canonical;
pub mod error;
pub mod objects;
pub mod store;

pub use error::CoreError;
