//! Rutas de archivo que el usuario eligió explícitamente (diálogo nativo o arrastrar y soltar).
//!
//! La UI no puede pedir la importación de una ruta arbitraria: `import_files` solo acepta rutas
//! presentes aquí, cada una se consume una sola vez y caduca a los pocos minutos.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant};

const TTL: Duration = Duration::from_secs(10 * 60);
const MAX_GRANTS: usize = 1000;

#[derive(Default)]
pub struct Grants {
    inner: Mutex<HashMap<PathBuf, Instant>>,
}

impl Grants {
    pub fn add<I: IntoIterator<Item = PathBuf>>(&self, paths: I) {
        let mut map = self.inner.lock().expect("grants lock");
        let now = Instant::now();
        map.retain(|_, t| now.duration_since(*t) < TTL);
        for p in paths {
            if map.len() >= MAX_GRANTS {
                break;
            }
            map.insert(p, now);
        }
    }

    /// Consume el permiso si existe y no ha caducado.
    pub fn take(&self, path: &Path) -> bool {
        let mut map = self.inner.lock().expect("grants lock");
        match map.remove(path) {
            Some(t) => t.elapsed() < TTL,
            None => false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grant_is_single_use() {
        let g = Grants::default();
        g.add([PathBuf::from("/Users/x/a.pdf")]);
        assert!(!g.take(Path::new("/Users/x/b.pdf")));
        assert!(g.take(Path::new("/Users/x/a.pdf")));
        assert!(!g.take(Path::new("/Users/x/a.pdf")));
    }

    #[test]
    fn expired_grants_are_rejected() {
        let g = Grants::default();
        let p = PathBuf::from("/tmp/a.txt");
        g.inner
            .lock()
            .unwrap()
            .insert(p.clone(), Instant::now() - TTL - Duration::from_secs(1));
        assert!(!g.take(&p));
    }
}
