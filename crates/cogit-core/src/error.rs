use std::fmt;

/// Error classes mirror the CLI exit-code contract of the reference
/// implementation: user errors (1) vs corruption (3).
#[derive(Debug)]
pub enum CoreError {
    User(String),
    Corruption(String),
    Io(std::io::Error),
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CoreError::User(msg) => write!(f, "{msg}"),
            CoreError::Corruption(msg) => write!(f, "corruption: {msg}"),
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
