//! Content-addressed object store: zlib(<type> <size>\0<canonical-json>).
//! Write: validate -> canonicalize -> hash -> tmp file -> atomic rename.
//! Read: decompress -> header -> size, hash, canonical-bytes, schema checks.

use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use flate2::read::ZlibDecoder;
use flate2::write::ZlibEncoder;
use flate2::Compression;
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::canonical::{canonical_json, parse_json};
use crate::error::{CoreError, Result};
use crate::objects::{encode_object, is_oid, validate_object, OBJECT_TYPES};

pub struct ObjectStore {
    objects_dir: PathBuf,
    tmp_dir: PathBuf,
}

impl ObjectStore {
    pub fn new(cogit_dir: &Path) -> Self {
        ObjectStore {
            objects_dir: cogit_dir.join("objects"),
            tmp_dir: cogit_dir.join("tmp"),
        }
    }

    pub fn path_for(&self, oid: &str) -> Result<PathBuf> {
        if !is_oid(oid) {
            return Err(CoreError::User(format!("object store: invalid object id '{oid}'")));
        }
        let hexpart = &oid[7..];
        Ok(self.objects_dir.join(&hexpart[..2]).join(&hexpart[2..]))
    }

    pub fn exists(&self, oid: &str) -> Result<bool> {
        Ok(self.path_for(oid)?.is_file())
    }

    /// Write an object; deduplicates by hash. Returns the object ID.
    pub fn write(&self, value: &Value) -> Result<String> {
        let (oid, preimage) = encode_object(value)?;
        let target = self.path_for(&oid)?;
        if target.exists() {
            let existing = self.read_preimage(&oid, &target)?;
            if existing != preimage {
                return Err(CoreError::Corruption(format!(
                    "object store: {oid} exists with different content (collision/corruption)"
                )));
            }
            return Ok(oid);
        }
        fs::create_dir_all(target.parent().expect("fanout parent"))?;
        fs::create_dir_all(&self.tmp_dir)?;

        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&preimage)?;
        let compressed = encoder.finish()?;

        let tmp_path = self.tmp_dir.join(format!(
            "obj-{}-{}",
            std::process::id(),
            &oid[7..19],
        ));
        {
            let mut file = fs::File::create(&tmp_path)?;
            file.write_all(&compressed)?;
            file.sync_all()?;
        }
        fs::rename(&tmp_path, &target)?;
        Ok(oid)
    }

    /// Read and fully verify an object.
    pub fn read(&self, oid: &str) -> Result<Value> {
        let target = self.path_for(oid)?;
        if !target.is_file() {
            return Err(CoreError::User(format!("object store: {oid} not found")));
        }
        let preimage = self.read_preimage(oid, &target)?;
        self.decode_preimage(oid, &preimage)
    }

    fn read_preimage(&self, oid: &str, path: &Path) -> Result<Vec<u8>> {
        let compressed = fs::read(path)?;
        let mut decoder = ZlibDecoder::new(compressed.as_slice());
        let mut preimage = Vec::new();
        decoder
            .read_to_end(&mut preimage)
            .map_err(|e| CoreError::Corruption(format!("object store: {oid} corrupt zlib body: {e}")))?;
        Ok(preimage)
    }

    fn decode_preimage(&self, oid: &str, preimage: &[u8]) -> Result<Value> {
        let nul = preimage
            .iter()
            .position(|b| *b == 0)
            .ok_or_else(|| CoreError::Corruption(format!("object store: {oid} malformed header (no NUL)")))?;
        let header = std::str::from_utf8(&preimage[..nul])
            .map_err(|_| CoreError::Corruption(format!("object store: {oid} malformed header")))?;
        let body = &preimage[nul + 1..];
        let (type_text, size_text) = header
            .split_once(' ')
            .ok_or_else(|| CoreError::Corruption(format!("object store: {oid} malformed header")))?;
        let declared_size: usize = size_text
            .parse()
            .map_err(|_| CoreError::Corruption(format!("object store: {oid} malformed header")))?;
        if !OBJECT_TYPES.contains(&type_text) {
            return Err(CoreError::Corruption(format!(
                "object store: {oid} unknown object type '{type_text}'"
            )));
        }
        if declared_size != body.len() {
            return Err(CoreError::Corruption(format!(
                "object store: {oid} size mismatch (declared {declared_size}, actual {})",
                body.len()
            )));
        }
        let digest = Sha256::digest(preimage);
        let mut computed = String::with_capacity(71);
        computed.push_str("sha256:");
        for byte in digest {
            computed.push_str(&format!("{byte:02x}"));
        }
        if computed != oid {
            return Err(CoreError::Corruption(format!(
                "object store: hash-path mismatch (path {oid}, content {computed})"
            )));
        }
        let body_text = std::str::from_utf8(body)
            .map_err(|_| CoreError::Corruption(format!("object store: {oid} invalid JSON body")))?;
        let value = parse_json(body_text)
            .map_err(|e| CoreError::Corruption(format!("object store: {oid} invalid JSON body: {e}")))?;
        let obj_type = validate_object(&value)
            .map_err(|e| CoreError::Corruption(format!("object store: {oid} schema invalid: {e}")))?;
        if canonical_json(&value)?.as_bytes() != body {
            return Err(CoreError::Corruption(format!(
                "object store: {oid} body is not canonical JSON"
            )));
        }
        if obj_type != type_text {
            return Err(CoreError::Corruption(format!(
                "object store: {oid} header/body type mismatch"
            )));
        }
        Ok(value)
    }
}
