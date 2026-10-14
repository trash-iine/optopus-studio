//! Progress while a run is under way.
//!
//! The core calls the objective probe every time the best solution improves. The probe is a
//! plain `fn`, so it cannot carry where to report to; the run being reported lives in a static
//! instead, set by [`watch`] around each run. The first improvement is sent at once; later ones
//! are held, and a ticker thread sends the latest held one every [`INTERVAL`], so a fast search
//! neither floods the backend nor leaves it showing a stale best.

use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use crate::protocol::WorkerEvent;

const INTERVAL: Duration = Duration::from_millis(100);

struct Live {
    run: usize,
    variant: usize,
    start: Instant,
    higher_is_better: bool,
    best: Option<f64>,
    held: Option<(f64, Instant)>,
}

impl Live {
    fn send(&self, objective: f64, at: Instant) {
        WorkerEvent::Progress {
            run: self.run,
            variant: self.variant,
            elapsed_secs: (at - self.start).as_secs_f64(),
            objective,
        }
        .emit();
    }
}

static LIVE: Mutex<Option<Live>> = Mutex::new(None);
static WATCHING: AtomicBool = AtomicBool::new(false);

fn with_live(f: impl FnOnce(&mut Live)) {
    // A poisoned lock only means a run panicked mid-report; progress is best effort.
    if let Ok(mut live) = LIVE.lock()
        && let Some(live) = live.as_mut()
    {
        f(live);
    }
}

/// Reports improvements of run `run` while `body` runs.
pub(crate) fn watch<T>(
    run: usize,
    variant: usize,
    start: Instant,
    higher_is_better: bool,
    body: impl FnOnce() -> T,
) -> T {
    if let Ok(mut live) = LIVE.lock() {
        *live = Some(Live {
            run,
            variant,
            start,
            higher_is_better,
            best: None,
            held: None,
        });
    }
    WATCHING.store(true, Ordering::SeqCst);
    let (stop, stopped) = mpsc::channel::<()>();
    let ticker = std::thread::spawn(move || {
        // Wakes every INTERVAL until the run ends, sending what was held meanwhile.
        while let Err(mpsc::RecvTimeoutError::Timeout) = stopped.recv_timeout(INTERVAL) {
            with_live(|live| {
                if let Some((objective, at)) = live.held.take() {
                    live.send(objective, at);
                }
            });
        }
    });
    let out = body();
    WATCHING.store(false, Ordering::SeqCst);
    let _ = stop.send(());
    let _ = ticker.join();
    if let Ok(mut live) = LIVE.lock() {
        // The run's last improvement, if it came within INTERVAL of the end.
        if let Some(live) = live.as_mut()
            && let Some((objective, at)) = live.held.take()
        {
            live.send(objective, at);
        }
        *live = None;
    }
    out
}

/// Called from the probe with the objective of a new best solution.
pub(crate) fn improved(objective: f64) {
    if !WATCHING.load(Ordering::Relaxed) {
        return;
    }
    with_live(|live| {
        // A sub-run reports its own best, which can be worse than the run's.
        let better = live.best.is_none_or(|best| {
            if live.higher_is_better {
                objective > best
            } else {
                objective < best
            }
        });
        if !better {
            return;
        }
        let now = Instant::now();
        if live.best.is_none() {
            live.send(objective, now);
        } else {
            live.held = Some((objective, now));
        }
        live.best = Some(objective);
    });
}
