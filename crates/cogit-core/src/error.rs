use std::fmt;

/// Error classes mirror the CLI exit-code contract
/// (docs/spec/cli-contract.md).
#[derive(Debug)]
pub enum CoreError {
    /// Invalid input, unresolved conflict, verification failure (exit 1).
    User(String),
    /// No repository found or invalid layout (exit 2).
    RepoNotFound(String),
    /// Corruption detected (exit 3).
    Corruption(String),
    /// Lock contention or old-target mismatch (exit 4).
    Concurrent(String),
    /// Unsupported repository format or extension (exit 5).
    Unsupported(String),
    /// Underlying IO failure (reported as exit 1).
    Io(std::io::Error),
}

impl CoreError {
    pub fn exit_code(&self) -> i32 {
        match self {
            CoreError::User(_) | CoreError::Io(_) => 1,
            CoreError::RepoNotFound(_) => 2,
            CoreError::Corruption(_) => 3,
            CoreError::Concurrent(_) => 4,
            CoreError::Unsupported(_) => 5,
        }
    }
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CoreError::User(msg)
            | CoreError::RepoNotFound(msg)
            | CoreError::Corruption(msg)
            | CoreError::Concurrent(msg)
            | CoreError::Unsupported(msg) => write!(f, "{msg}"),
            CoreError::Io(err) => write!(f, "io: {err}"),
        }
    }
}

impl std::error::Error for CoreError {}

impl From<std::io::Error> for CoreError {
    fn from(err: std::io::Error) -> Self {
        CoreError::Io(err)
    }
}

pub type Result<T> = std::result::Result<T, CoreError>;
