//! Grabación nativa del micrófono (ADR-003).
//!
//! - Un hilo dedicado posee el stream de CoreAudio (cpal) y escribe segmentos WAV de 60 s
//!   (`seg_0001.wav`, …) en `recordings/<uuid>/`, más un `manifest.json`.
//! - Cada segundo se vacía el WAV a disco con su cabecera actualizada: si la app se cierra de
//!   golpe se pierde como mucho ~1 s, y al reabrir la grabación aparece como recuperable.
//! - Al parar, los segmentos se unen en `recording.wav` y el núcleo lo importa como fuente
//!   `recording`; solo entonces se borra la carpeta temporal.

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, SampleFormat, SizedSample};
use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, SyncSender, TryRecvError};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter};

pub const STATUS_EVENT: &str = "recording://status";
const SEGMENT_SECONDS: u64 = 60;
const MAX_SECONDS: u64 = 6 * 3600;
const WAV_HEADER: u64 = 44;

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Target {
    pub subject_id: String,
    pub title: String,
    #[serde(default)]
    pub unit_ids: Vec<String>,
    #[serde(default)]
    pub session_ids: Vec<String>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
struct Manifest {
    version: u32,
    id: String,
    target: Target,
    started_at_ms: u64,
    sample_rate: u32,
    device: String,
    closed: bool,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum State {
    Idle,
    Recording,
    Paused,
}

#[derive(Serialize, Clone, Debug)]
pub struct Status {
    pub state: State,
    pub id: Option<String>,
    pub title: Option<String>,
    pub subject_id: Option<String>,
    pub elapsed_ms: u64,
    pub level: f32,
    pub device: Option<String>,
    pub error: Option<String>,
}

#[derive(Serialize)]
pub struct InputDevice {
    pub id: String,
    pub name: String,
    pub is_default: bool,
}

#[derive(Serialize, Clone)]
pub struct Recoverable {
    pub id: String,
    pub title: String,
    pub subject_id: String,
    pub started_at_ms: u64,
    pub duration_ms: u64,
}

enum Ctl {
    Pause,
    Resume,
    Stop,
}

/// Datos compartidos entre el hilo de grabación y los comandos.
#[derive(Default)]
struct Shared {
    frames: AtomicU64,
    peak: AtomicU32,
    paused: AtomicBool,
    dropped: AtomicU64,
    error: Mutex<Option<String>>,
}

struct Active {
    manifest: Manifest,
    ctl: mpsc::Sender<Ctl>,
    shared: Arc<Shared>,
    thread: JoinHandle<Result<(), String>>,
}

pub struct Recorder {
    root: PathBuf,
    active: Mutex<Option<Active>>,
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or_default()
}

fn new_id() -> Result<String, String> {
    let mut b = [0u8; 16];
    File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut b))
        .map_err(|e| e.to_string())?;
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let h: String = b.iter().map(|x| format!("{x:02x}")).collect();
    Ok(format!(
        "{}-{}-{}-{}-{}",
        &h[0..8],
        &h[8..12],
        &h[12..16],
        &h[16..20],
        &h[20..32]
    ))
}

/// Los ids de carpeta vienen de la UI en recuperar/descartar: solo UUID, nunca rutas.
fn valid_id(id: &str) -> bool {
    id.len() == 36
        && id.chars().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => c == '-',
            _ => c.is_ascii_hexdigit(),
        })
}

fn write_private(path: &Path, data: &[u8]) -> std::io::Result<()> {
    let tmp = path.with_extension("tmp");
    {
        let mut f = File::create(&tmp)?;
        f.write_all(data)?;
        f.sync_all()?;
    }
    fs::rename(tmp, path)
}

fn save_manifest(dir: &Path, m: &Manifest) -> Result<(), String> {
    let data = serde_json::to_vec_pretty(m).map_err(|e| e.to_string())?;
    write_private(&dir.join("manifest.json"), &data).map_err(|e| e.to_string())
}

fn segment_path(dir: &Path, n: u32) -> PathBuf {
    dir.join(format!("seg_{n:04}.wav"))
}

fn segments(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = fs::read_dir(dir)
        .map(|it| {
            it.filter_map(|e| e.ok().map(|e| e.path()))
                .filter(|p| {
                    p.file_name()
                        .and_then(|n| n.to_str())
                        .is_some_and(|n| n.starts_with("seg_") && n.ends_with(".wav"))
                })
                .collect()
        })
        .unwrap_or_default();
    v.sort();
    v
}

/// Corrige la cabecera de un WAV PCM16 mono que quedó a medias (cierre inesperado).
/// Devuelve los bytes de audio válidos.
pub fn repair_wav(path: &Path) -> std::io::Result<u64> {
    let mut f = OpenOptions::new().read(true).write(true).open(path)?;
    let len = f.metadata()?.len();
    if len < WAV_HEADER {
        return Ok(0);
    }
    let mut head = [0u8; 44];
    f.read_exact(&mut head)?;
    if &head[0..4] != b"RIFF" || &head[8..12] != b"WAVE" || &head[36..40] != b"data" {
        return Err(std::io::Error::other("cabecera WAV inesperada"));
    }
    let data = (len - WAV_HEADER) & !1; // múltiplo de 2 bytes (una muestra)
    f.seek(SeekFrom::Start(4))?;
    f.write_all(&((data + 36) as u32).to_le_bytes())?;
    f.seek(SeekFrom::Start(40))?;
    f.write_all(&(data as u32).to_le_bytes())?;
    f.set_len(WAV_HEADER + data)?;
    f.sync_all()?;
    Ok(data)
}

fn wav_header(sample_rate: u32, data_bytes: u64) -> Vec<u8> {
    let mut h = Vec::with_capacity(44);
    h.extend_from_slice(b"RIFF");
    h.extend_from_slice(&((data_bytes + 36) as u32).to_le_bytes());
    h.extend_from_slice(b"WAVEfmt ");
    h.extend_from_slice(&16u32.to_le_bytes());
    h.extend_from_slice(&1u16.to_le_bytes()); // PCM
    h.extend_from_slice(&1u16.to_le_bytes()); // mono
    h.extend_from_slice(&sample_rate.to_le_bytes());
    h.extend_from_slice(&(sample_rate * 2).to_le_bytes());
    h.extend_from_slice(&2u16.to_le_bytes());
    h.extend_from_slice(&16u16.to_le_bytes());
    h.extend_from_slice(b"data");
    h.extend_from_slice(&(data_bytes as u32).to_le_bytes());
    h
}

/// Une los segmentos (reparados) en un único WAV. Devuelve (ruta, duración en ms).
pub fn concat(dir: &Path, sample_rate: u32) -> Result<(PathBuf, u64), String> {
    let segs = segments(dir);
    let mut total = 0u64;
    for s in &segs {
        total += repair_wav(s).map_err(|e| format!("Segmento dañado: {e}"))?;
    }
    if total == 0 {
        return Err("La grabación está vacía".into());
    }
    if total + 36 > u32::MAX as u64 {
        return Err("La grabación es demasiado grande".into());
    }
    let out_path = dir.join("recording.wav");
    let mut out = File::create(&out_path).map_err(|e| e.to_string())?;
    out.write_all(&wav_header(sample_rate, total))
        .map_err(|e| e.to_string())?;
    for s in &segs {
        let mut f = File::open(s).map_err(|e| e.to_string())?;
        f.seek(SeekFrom::Start(WAV_HEADER))
            .map_err(|e| e.to_string())?;
        std::io::copy(&mut f, &mut out).map_err(|e| e.to_string())?;
    }
    out.sync_all().map_err(|e| e.to_string())?;
    Ok((out_path, total / 2 * 1000 / sample_rate.max(1) as u64))
}

fn find_device(host: &cpal::Host, id: Option<&str>) -> Result<cpal::Device, String> {
    if let Some(id) = id {
        let wanted: cpal::DeviceId = id.parse().map_err(|_| "Micrófono no válido")?;
        if let Some(d) = host.device_by_id(&wanted) {
            return Ok(d);
        }
        return Err("El micrófono elegido ya no está conectado".into());
    }
    host.default_input_device()
        .ok_or_else(|| "No hay ningún micrófono disponible".to_string())
}

fn device_name(d: &cpal::Device) -> String {
    d.description()
        .map(|x| x.name().to_string())
        .unwrap_or_else(|_| "Micrófono".into())
}

pub fn list_devices() -> Result<Vec<InputDevice>, String> {
    let host = cpal::default_host();
    let default_id = host.default_input_device().and_then(|d| d.id().ok());
    let devices = host
        .input_devices()
        .map_err(|e| format!("No se pudieron listar los micrófonos: {e}"))?;
    Ok(devices
        .filter_map(|d| {
            let id = d.id().ok()?;
            Some(InputDevice {
                is_default: default_id.as_ref() == Some(&id),
                name: device_name(&d),
                id: id.to_string(),
            })
        })
        .collect())
}

/// Convierte cada bloque a mono f32 y lo pasa al hilo escritor sin bloquear el audio.
fn build_stream<T>(
    device: &cpal::Device,
    config: cpal::StreamConfig,
    tx: SyncSender<Vec<f32>>,
    shared: Arc<Shared>,
) -> Result<cpal::Stream, String>
where
    T: SizedSample,
    f32: FromSample<T>,
{
    let channels = config.channels.max(1) as usize;
    let err_shared = shared.clone();
    device
        .build_input_stream::<T, _, _>(
            config,
            move |data: &[T], _| {
                let mono: Vec<f32> = data
                    .chunks(channels)
                    .map(|frame| {
                        frame.iter().map(|s| s.to_sample::<f32>()).sum::<f32>() / channels as f32
                    })
                    .collect();
                let peak = mono.iter().fold(0f32, |m, s| m.max(s.abs()));
                let prev = f32::from_bits(shared.peak.load(Ordering::Relaxed));
                if peak > prev {
                    shared.peak.store(peak.to_bits(), Ordering::Relaxed);
                }
                if tx.try_send(mono).is_err() {
                    shared.dropped.fetch_add(1, Ordering::Relaxed);
                }
            },
            move |e| {
                *err_shared.error.lock().expect("error lock") =
                    Some(format!("Se interrumpió el audio del micrófono: {e}"));
            },
            None,
        )
        .map_err(|e| format!("No se pudo abrir el micrófono: {e}"))
}

struct SegmentWriter {
    dir: PathBuf,
    rate: u32,
    index: u32,
    frames_in_segment: u64,
    writer: hound::WavWriter<std::io::BufWriter<File>>,
}

impl SegmentWriter {
    fn open(
        dir: &Path,
        rate: u32,
        index: u32,
    ) -> Result<hound::WavWriter<std::io::BufWriter<File>>, String> {
        let spec = hound::WavSpec {
            channels: 1,
            sample_rate: rate,
            bits_per_sample: 16,
            sample_format: hound::SampleFormat::Int,
        };
        hound::WavWriter::create(segment_path(dir, index), spec)
            .map_err(|e| format!("No se pudo escribir la grabación: {e}"))
    }

    fn new(dir: &Path, rate: u32) -> Result<Self, String> {
        Ok(Self {
            dir: dir.to_path_buf(),
            rate,
            index: 1,
            frames_in_segment: 0,
            writer: Self::open(dir, rate, 1)?,
        })
    }

    fn write(&mut self, samples: &[f32]) -> Result<(), String> {
        for s in samples {
            let v = (s.clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
            self.writer.write_sample(v).map_err(|e| e.to_string())?;
            self.frames_in_segment += 1;
            if self.frames_in_segment >= SEGMENT_SECONDS * self.rate as u64 {
                self.rotate()?;
            }
        }
        Ok(())
    }

    fn rotate(&mut self) -> Result<(), String> {
        self.index += 1;
        let next = Self::open(&self.dir, self.rate, self.index)?;
        let old = std::mem::replace(&mut self.writer, next);
        old.finalize().map_err(|e| e.to_string())?;
        self.frames_in_segment = 0;
        Ok(())
    }

    fn flush(&mut self) -> Result<(), String> {
        self.writer.flush().map_err(|e| e.to_string())
    }

    fn finish(self) -> Result<(), String> {
        self.writer.finalize().map_err(|e| e.to_string())
    }
}

/// Hilo de grabación: posee el stream (no es `Send`) y el escritor de segmentos.
fn run(
    app: AppHandle,
    device: cpal::Device,
    dir: PathBuf,
    mut manifest: Manifest,
    shared: Arc<Shared>,
    ctl: Receiver<Ctl>,
    ready: mpsc::Sender<Result<(), String>>,
) -> Result<(), String> {
    let setup = (|| -> Result<_, String> {
        let supported = device
            .default_input_config()
            .map_err(|e| format!("El micrófono no ofrece una configuración válida: {e}"))?;
        let config = supported.config();
        let rate = config.sample_rate;
        let (tx, rx) = mpsc::sync_channel::<Vec<f32>>(1024);
        let stream = match supported.sample_format() {
            SampleFormat::F32 => build_stream::<f32>(&device, config, tx, shared.clone()),
            SampleFormat::I16 => build_stream::<i16>(&device, config, tx, shared.clone()),
            SampleFormat::I32 => build_stream::<i32>(&device, config, tx, shared.clone()),
            SampleFormat::U16 => build_stream::<u16>(&device, config, tx, shared.clone()),
            other => Err(format!("Formato de micrófono no compatible: {other}")),
        }?;
        manifest.sample_rate = rate;
        save_manifest(&dir, &manifest)?;
        let writer = SegmentWriter::new(&dir, rate)?;
        stream
            .play()
            .map_err(|e| format!("No se pudo iniciar la grabación: {e}"))?;
        Ok((stream, rx, writer, rate))
    })();
    let (stream, rx, mut writer, rate) = match setup {
        Ok(v) => {
            let _ = ready.send(Ok(()));
            v
        }
        Err(e) => {
            let _ = ready.send(Err(e.clone()));
            return Err(e);
        }
    };

    let mut last_flush = Instant::now();
    let mut last_emit = Instant::now();
    let result = loop {
        match ctl.try_recv() {
            Ok(Ctl::Stop) | Err(TryRecvError::Disconnected) => break Ok(()),
            Ok(Ctl::Pause) => {
                let _ = stream.pause();
                shared.paused.store(true, Ordering::Relaxed);
            }
            Ok(Ctl::Resume) => {
                if stream.play().is_ok() {
                    shared.paused.store(false, Ordering::Relaxed);
                }
            }
            Err(TryRecvError::Empty) => {}
        }
        match rx.recv_timeout(Duration::from_millis(50)) {
            Ok(block) => {
                if let Err(e) = writer.write(&block) {
                    break Err(e);
                }
                shared
                    .frames
                    .fetch_add(block.len() as u64, Ordering::Relaxed);
            }
            Err(RecvTimeoutError::Timeout) => {}
            Err(RecvTimeoutError::Disconnected) => break Ok(()),
        }
        if last_flush.elapsed() >= Duration::from_secs(1) {
            if let Err(e) = writer.flush() {
                break Err(e);
            }
            last_flush = Instant::now();
        }
        if shared.frames.load(Ordering::Relaxed) >= MAX_SECONDS * rate as u64 {
            *shared.error.lock().expect("error lock") =
                Some("Se alcanzó el máximo de 6 horas; la grabación se detuvo.".into());
            break Ok(());
        }
        if last_emit.elapsed() >= Duration::from_millis(150) {
            let _ = app.emit(STATUS_EVENT, snapshot(&manifest, &shared, rate));
            last_emit = Instant::now();
        }
    };
    drop(stream);
    // Lo que quedó en el canal también se guarda.
    while let Ok(block) = rx.try_recv() {
        let _ = writer.write(&block);
        shared
            .frames
            .fetch_add(block.len() as u64, Ordering::Relaxed);
    }
    writer.finish()?;
    manifest.closed = true;
    save_manifest(&dir, &manifest)?;
    result
}

fn snapshot(m: &Manifest, shared: &Shared, rate: u32) -> Status {
    let level = f32::from_bits(shared.peak.swap(0, Ordering::Relaxed));
    Status {
        state: if shared.paused.load(Ordering::Relaxed) {
            State::Paused
        } else {
            State::Recording
        },
        id: Some(m.id.clone()),
        title: Some(m.target.title.clone()),
        subject_id: Some(m.target.subject_id.clone()),
        elapsed_ms: shared.frames.load(Ordering::Relaxed) * 1000 / rate.max(1) as u64,
        level: level.min(1.0),
        device: Some(m.device.clone()),
        error: shared.error.lock().expect("error lock").clone(),
    }
}

impl Recorder {
    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            active: Mutex::new(None),
        }
    }

    pub fn status(&self) -> Status {
        let guard = self.active.lock().expect("recorder lock");
        match guard.as_ref() {
            Some(a) => snapshot(&a.manifest, &a.shared, a.manifest.sample_rate.max(1)),
            None => Status {
                state: State::Idle,
                id: None,
                title: None,
                subject_id: None,
                elapsed_ms: 0,
                level: 0.0,
                device: None,
                error: None,
            },
        }
    }

    pub fn start(
        &self,
        app: AppHandle,
        device_id: Option<String>,
        target: Target,
    ) -> Result<Status, String> {
        let mut guard = self.active.lock().expect("recorder lock");
        if guard.is_some() {
            return Err("Ya hay una grabación en curso".into());
        }
        let host = cpal::default_host();
        let device = find_device(&host, device_id.as_deref())?;
        let id = new_id()?;
        let dir = self.root.join(&id);
        fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        set_private(&self.root);
        set_private(&dir);
        let manifest = Manifest {
            version: 1,
            id: id.clone(),
            target,
            started_at_ms: now_ms(),
            sample_rate: 0,
            device: device_name(&device),
            closed: false,
        };
        let shared = Arc::new(Shared::default());
        let (ctl_tx, ctl_rx) = mpsc::channel();
        let (ready_tx, ready_rx) = mpsc::channel();
        let thread = {
            let (dir, manifest, shared) = (dir.clone(), manifest.clone(), shared.clone());
            std::thread::Builder::new()
                .name("recorder".into())
                .spawn(move || run(app, device, dir, manifest, shared, ctl_rx, ready_tx))
                .map_err(|e| e.to_string())?
        };
        match ready_rx.recv_timeout(Duration::from_secs(10)) {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                let _ = thread.join();
                let _ = fs::remove_dir_all(&dir);
                return Err(e);
            }
            Err(_) => return Err("El micrófono no respondió".into()),
        }
        let mut manifest = manifest;
        manifest.sample_rate = read_manifest(&dir).map(|m| m.sample_rate).unwrap_or(48_000);
        *guard = Some(Active {
            manifest,
            ctl: ctl_tx,
            shared,
            thread,
        });
        drop(guard);
        Ok(self.status())
    }

    pub fn pause(&self, resume: bool) -> Result<Status, String> {
        {
            let guard = self.active.lock().expect("recorder lock");
            let a = guard.as_ref().ok_or("No hay ninguna grabación en curso")?;
            a.ctl
                .send(if resume { Ctl::Resume } else { Ctl::Pause })
                .map_err(|_| "La grabación se detuvo")?;
        }
        std::thread::sleep(Duration::from_millis(60));
        Ok(self.status())
    }

    /// Detiene y cierra los archivos. Devuelve (carpeta, manifiesto) para importarlos.
    pub fn stop(&self) -> Result<(String, Option<String>), String> {
        let active = self
            .active
            .lock()
            .expect("recorder lock")
            .take()
            .ok_or("No hay ninguna grabación en curso")?;
        let _ = active.ctl.send(Ctl::Stop);
        let joined = active
            .thread
            .join()
            .map_err(|_| "El hilo de grabación falló".to_string())?;
        let warning = active.shared.error.lock().expect("error lock").clone();
        joined?;
        Ok((active.manifest.id, warning))
    }

    /// Al cerrar la app: cierra los archivos; la grabación quedará como recuperable.
    pub fn shutdown(&self) {
        if let Some(a) = self.active.lock().expect("recorder lock").take() {
            let _ = a.ctl.send(Ctl::Stop);
            let _ = a.thread.join();
        }
    }

    pub fn active_id(&self) -> Option<String> {
        self.active
            .lock()
            .expect("recorder lock")
            .as_ref()
            .map(|a| a.manifest.id.clone())
    }

    pub fn dir(&self, id: &str) -> Result<PathBuf, String> {
        if !valid_id(id) {
            return Err("Grabación no válida".into());
        }
        Ok(self.root.join(id))
    }

    /// Datos para cerrar una grabación detenida o interrumpida: (carpeta, destino, Hz).
    pub fn pending(&self, id: &str) -> Result<(PathBuf, Target, u32), String> {
        if self.active_id().as_deref() == Some(id) {
            return Err("La grabación sigue en curso".into());
        }
        let dir = self.dir(id)?;
        let m = read_manifest(&dir).ok_or("No se encontró la grabación")?;
        Ok((dir, m.target, m.sample_rate))
    }

    pub fn recoverable(&self) -> Vec<Recoverable> {
        let active = self.active_id();
        let Ok(entries) = fs::read_dir(&self.root) else {
            return vec![];
        };
        let mut out: Vec<Recoverable> = entries
            .filter_map(|e| e.ok())
            .filter_map(|e| {
                let name = e.file_name().to_str()?.to_string();
                if !valid_id(&name) || active.as_deref() == Some(name.as_str()) {
                    return None;
                }
                let m = read_manifest(&e.path())?;
                let bytes: u64 = segments(&e.path())
                    .iter()
                    .filter_map(|p| p.metadata().ok())
                    .map(|md| md.len().saturating_sub(WAV_HEADER))
                    .sum();
                Some(Recoverable {
                    id: name,
                    title: m.target.title,
                    subject_id: m.target.subject_id,
                    started_at_ms: m.started_at_ms,
                    duration_ms: bytes / 2 * 1000 / m.sample_rate.max(1) as u64,
                })
            })
            .collect();
        out.sort_by_key(|r| r.started_at_ms);
        out
    }

    pub fn discard(&self, id: &str) -> Result<(), String> {
        if self.active_id().as_deref() == Some(id) {
            return Err("No se puede descartar la grabación en curso".into());
        }
        let dir = self.dir(id)?;
        if dir.is_dir() {
            fs::remove_dir_all(dir).map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}

fn read_manifest(dir: &Path) -> Option<Manifest> {
    let data = fs::read(dir.join("manifest.json")).ok()?;
    serde_json::from_slice(&data).ok()
}

fn set_private(p: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = fs::set_permissions(p, fs::Permissions::from_mode(0o700));
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("sa-rec-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    fn write_seg(dir: &Path, n: u32, samples: &[i16], finalize: bool) {
        let mut w = SegmentWriter::open(dir, 16_000, n).unwrap();
        for s in samples {
            w.write_sample(*s).unwrap();
        }
        if finalize {
            w.finalize().unwrap();
        } else {
            w.flush().unwrap();
            std::mem::forget(w); // simula un cierre brusco sin finalizar
        }
    }

    #[test]
    fn ids_are_uuid_only() {
        assert!(valid_id(&new_id().unwrap()));
        assert!(!valid_id("../../etc"));
        assert!(!valid_id("0123456789abcdef0123456789abcdef0123"));
    }

    #[test]
    fn repairs_truncated_segment_and_concatenates() {
        let dir = tmpdir("concat");
        write_seg(&dir, 1, &vec![1000i16; 16_000], true);
        write_seg(&dir, 2, &vec![-1000i16; 8_000], false);
        // Cabecera desactualizada + medio frame colgando, como tras un `kill -9`.
        let p = segment_path(&dir, 2);
        let mut f = OpenOptions::new().append(true).open(&p).unwrap();
        f.write_all(&[0x7f]).unwrap();
        drop(f);
        let (wav, ms) = concat(&dir, 16_000).unwrap();
        assert_eq!(ms, 1500);
        let r = hound::WavReader::open(wav).unwrap();
        assert_eq!(r.spec().sample_rate, 16_000);
        assert_eq!(r.len(), 24_000);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn hound_header_is_44_bytes() {
        let dir = tmpdir("header");
        write_seg(&dir, 1, &[1, 2, 3], true);
        let bytes = fs::read(segment_path(&dir, 1)).unwrap();
        assert_eq!(&bytes[36..40], b"data");
        assert_eq!(bytes.len(), 44 + 6);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn recoverable_lists_interrupted_recordings() {
        let root = tmpdir("recover");
        let rec = Recorder::new(root.clone());
        let id = new_id().unwrap();
        let dir = root.join(&id);
        fs::create_dir_all(&dir).unwrap();
        let m = Manifest {
            version: 1,
            id: id.clone(),
            target: Target {
                subject_id: "s".into(),
                title: "Clase".into(),
                unit_ids: vec![],
                session_ids: vec![],
            },
            started_at_ms: 1,
            sample_rate: 16_000,
            device: "Mic".into(),
            closed: false,
        };
        save_manifest(&dir, &m).unwrap();
        write_seg(&dir, 1, &vec![0i16; 32_000], false);
        fs::create_dir_all(root.join("no-es-un-id")).unwrap();
        let list = rec.recoverable();
        assert_eq!(list.len(), 1);
        assert_eq!(list[0].duration_ms, 2000);
        assert!(rec.discard("../x").is_err());
        rec.discard(&id).unwrap();
        assert!(rec.recoverable().is_empty());
        let _ = fs::remove_dir_all(root);
    }
}
