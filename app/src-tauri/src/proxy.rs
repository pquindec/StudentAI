//! Cliente HTTP/1.1 mínimo sobre Unix socket hacia el backend Python.

use bytes::Bytes;
use http_body_util::{BodyExt, Full, Limited};
use hyper::{Method, Request};
use hyper_util::rt::TokioIo;
use std::path::Path;
use tokio::net::UnixStream;

/// Tamaño máximo de una respuesta JSON del backend.
const MAX_RESPONSE_BYTES: usize = 32 * 1024 * 1024;
const MAX_PATH_LEN: usize = 2048;

pub struct Response {
    pub status: u16,
    pub body: Bytes,
}

/// Valida la ruta pedida por el frontend: solo la API versionada, sin trucos de ruta.
pub fn validate_path(path: &str) -> Result<(), String> {
    let ok = path.starts_with("/api/v1/")
        && path.len() <= MAX_PATH_LEN
        && !path.contains("..")
        && !path.contains('#')
        && !path.contains('\\')
        && path.chars().all(|c| c.is_ascii_graphic());
    if ok {
        Ok(())
    } else {
        Err("Ruta de API no permitida".into())
    }
}

pub fn parse_method(method: &str) -> Result<Method, String> {
    match method {
        "GET" => Ok(Method::GET),
        "POST" => Ok(Method::POST),
        "PUT" => Ok(Method::PUT),
        "PATCH" => Ok(Method::PATCH),
        "DELETE" => Ok(Method::DELETE),
        _ => Err("Método HTTP no permitido".into()),
    }
}

pub async fn send(
    socket: &Path,
    token: &str,
    method: Method,
    path: &str,
    json_body: Option<Vec<u8>>,
) -> Result<Response, String> {
    let stream = UnixStream::connect(socket)
        .await
        .map_err(|e| format!("No se pudo conectar con el backend: {e}"))?;
    let (mut sender, conn) = hyper::client::conn::http1::handshake(TokioIo::new(stream))
        .await
        .map_err(|e| format!("Error de conexión con el backend: {e}"))?;
    tokio::spawn(async move {
        let _ = conn.await;
    });

    let mut builder = Request::builder()
        .method(method)
        .uri(path)
        .header("host", "backend")
        .header("authorization", format!("Bearer {token}"))
        .header("accept", "application/json");
    if json_body.is_some() {
        builder = builder.header("content-type", "application/json");
    }
    let req = builder
        .body(Full::new(Bytes::from(json_body.unwrap_or_default())))
        .map_err(|e| e.to_string())?;

    let res = sender
        .send_request(req)
        .await
        .map_err(|e| format!("El backend no respondió: {e}"))?;
    let status = res.status().as_u16();
    let body = Limited::new(res.into_body(), MAX_RESPONSE_BYTES)
        .collect()
        .await
        .map_err(|_| "Respuesta del backend demasiado grande o incompleta".to_string())?
        .to_bytes();
    Ok(Response { status, body })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_api_paths() {
        assert!(validate_path("/api/v1/health").is_ok());
        assert!(validate_path("/api/v1/subjects?archived=false").is_ok());
    }

    #[test]
    fn rejects_unsafe_paths() {
        for p in [
            "/health",
            "/api/v2/x",
            "/api/v1/../admin",
            "/api/v1/a b",
            "/api/v1/x#frag",
            "/api/v1/\\x",
            "http://evil/api/v1/",
            "/api/v1/ñ",
        ] {
            assert!(validate_path(p).is_err(), "{p} debería rechazarse");
        }
        assert!(validate_path(&format!("/api/v1/{}", "a".repeat(3000))).is_err());
    }

    #[test]
    fn only_known_methods() {
        assert!(parse_method("GET").is_ok());
        assert!(parse_method("TRACE").is_err());
        assert!(parse_method("get").is_err());
    }
}
