//! Cogit core: canonical JSON, object schemas, and the content-addressed
//! object store. Contract: docs/spec/object-format-v1.md; object identity
//! is frozen by prototype/vectors/object-vectors-v1.json (ADR-0010) and
//! this crate must reproduce those IDs byte-for-byte.

pub mod bisect;
pub mod canonical;
pub mod error;
pub mod index;
pub mod maintenance;
pub mod objects;
pub mod refs;
pub mod repo;
pub mod rerere;
pub mod secrets;
pub mod store;
pub mod time;
pub mod verify;

pub use error::CoreError;
