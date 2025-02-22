//
//! Copyright 2020 Alibaba Group Holding Limited.
//! 
//! Licensed under the Apache License, Version 2.0 (the "License");
//! you may not use this file except in compliance with the License.
//! You may obtain a copy of the License at
//! 
//! http://www.apache.org/licenses/LICENSE-2.0
//! 
//! Unless required by applicable law or agreed to in writing, software
//! distributed under the License is distributed on an "AS IS" BASIS,
//! WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//! See the License for the specific language governing permissions and
//! limitations under the License.

use crate::JobConf;
use std::cell::Cell;
use std::fmt::Debug;

#[derive(Copy, Clone, Hash)]
pub struct WorkerId {
    /// The sequence number of the job this worker belongs to;
    pub job_id: u64,
    /// The number of total worker peers this job consist of;
    pub peers: u32,
    /// The index of this worker among all peers;
    pub index: u32,
    /// Indicates that if trace is enabled;
    pub trace_enable: bool,
}

impl WorkerId {
    pub fn new(job_id: u64, peers: u32, index: u32, trace: bool) -> Self {
        WorkerId { job_id, peers, index, trace_enable: trace }
    }

    pub fn all_peers(&self) -> WorkerIdIter {
        WorkerIdIter {
            job_id: self.job_id,
            peers: self.peers,
            cursor: 0,
            trace_enable: self.trace_enable,
            last: self.peers,
        }
    }
}

impl Debug for WorkerId {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "[worker_{}({}-{})]", self.index, self.job_id, self.peers)
    }
}

impl std::convert::From<&JobConf> for WorkerId {
    fn from(job_conf: &JobConf) -> Self {
        WorkerId {
            job_id: job_conf.job_id,
            peers: job_conf.total_workers() as u32,
            index: 0,
            trace_enable: job_conf.trace_enable,
        }
    }
}

impl PartialEq for WorkerId {
    fn eq(&self, other: &Self) -> bool {
        self.index == other.index && self.job_id == other.job_id
    }
}

impl Eq for WorkerId {}

pub struct WorkerIdIter {
    job_id: u64,
    peers: u32,
    trace_enable: bool,
    cursor: u32,
    last: u32,
}

impl WorkerIdIter {
    pub fn new(job_id: u64, peers: u32, start: u32, last: u32) -> Self {
        WorkerIdIter { job_id, peers, trace_enable: false, cursor: start, last }
    }

    pub fn enable_trace(&mut self) {
        self.trace_enable = true;
    }
}

impl Iterator for WorkerIdIter {
    type Item = WorkerId;

    fn next(&mut self) -> Option<Self::Item> {
        if self.cursor == self.last {
            None
        } else {
            let next = WorkerId::new(self.job_id, self.peers, self.cursor, self.trace_enable);
            self.cursor += 1;
            Some(next)
        }
    }
}

thread_local! {
    pub static CURRENT_WORKER : Cell<Option<WorkerId>> = Cell::new(None)
}

pub struct CurWorkerGuard;

impl CurWorkerGuard {
    pub fn new(id: WorkerId) -> Self {
        set_current_worker(Some(id));
        CurWorkerGuard
    }
}

impl Drop for CurWorkerGuard {
    fn drop(&mut self) {
        set_current_worker(None);
    }
}

#[inline]
pub fn guard(worker_id: WorkerId) -> CurWorkerGuard {
    CurWorkerGuard::new(worker_id)
}

#[inline]
fn set_current_worker(worker_id: Option<WorkerId>) {
    CURRENT_WORKER.with(|w| w.set(worker_id))
}

#[inline]
pub fn get_current_worker() -> Option<WorkerId> {
    CURRENT_WORKER.with(|w| w.get())
}

#[inline]
pub fn get_current_worker_uncheck() -> WorkerId {
    CURRENT_WORKER.with(|w| w.get()).expect("current worker lost;")
}

#[inline]
pub fn is_in_trace() -> bool {
    CURRENT_WORKER.with(|w| w.get().map(|w| w.trace_enable)).unwrap_or(false)
        || log_enabled!(log::Level::Trace)
}

macro_rules! inspect_worker {
    ($lvl:expr, $arg0: expr) => (
        if log_enabled!($lvl) {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                log!($lvl, concat!("{:?}: ", $arg0), id);
            } else {
                log!($lvl, $arg0);
            }
        } else if $lvl == log::Level::Info {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                println!(concat!("{:?}: ", $arg0), id);
            } else {
                println!($arg0);
            }
        }
    );
    ($lvl: expr, $arg0: expr, $($arg:tt)*) => (
        if log_enabled!($lvl) {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                log!($lvl, concat!("{:?}: ", $arg0), id, $($arg)*);
            } else {
                log!($lvl, $arg0, $($arg)*);
            }
        } else if $lvl == log::Level::Info {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                println!(concat!("{:?}: ", $arg0), id, $($arg)*);
            } else {
                println!($arg0, $($arg)*);
            }
        }
    )
}

#[macro_export]
macro_rules! info_worker {
    ($arg0:expr) => (
        inspect_worker!(log::Level::Info, $arg0);
    );
    ($arg0: expr, $($arg:tt)*) => (
        inspect_worker!(log::Level::Info, $arg0, $($arg)*);
    )
}

#[macro_export]
macro_rules! debug_worker {
    ($arg0:expr) => (
        inspect_worker!(log::Level::Debug, $arg0);
    );
    ($arg0: expr, $($arg:tt)*) => (
        inspect_worker!(log::Level::Debug, $arg0, $($arg)*);
    )
}

#[macro_export]
macro_rules! trace_worker {
    ($arg0:expr) => (
        inspect_worker!(log::Level::Trace, $arg0);
    );
    ($arg0: expr, $($arg:tt)*) => (
        inspect_worker!(log::Level::Trace, $arg0, $($arg)*);
    )
}

macro_rules! inspect_worker_error {
     ($lvl:expr, $arg0: expr) => (
        if log_enabled!($lvl) {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                log!($lvl, concat!("{:?}: ", $arg0), id);
            } else {
                log!($lvl, $arg0, $($arg)*);
            }
        } else {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                eprintln!(concat!("{:?}: ", $arg0), id);
            } else {
                eprintln!($arg0);
            }
        }
    );
    ($lvl: expr, $arg0: expr, $($arg:tt)*) => (
         if log_enabled!($lvl) {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                log!($lvl, concat!("{:?}: ", $arg0), id, $($arg)*);
            } else {
                log!(log::Level::Warn, $arg0, $($arg)*);
            }
         } else {
            if let Some(id) = $crate::worker_id::get_current_worker() {
                eprintln!(concat!("{:?}: ", $arg0), id, $($arg)*);
            } else {
                eprintln!($arg0, $($arg)*);
            }
         }
    )
}

#[macro_export]
macro_rules! error_worker {
    ($arg0:expr) => (
        inspect_worker!(log::Level::Error, $arg0);
    );
    ($arg0: expr, $($arg:tt)*) => (
        inspect_worker_error!(log::Level::Error, $arg0, $($arg)*);
    )
}

#[macro_export]
macro_rules! warn_worker {
    ($arg0:expr) => (
        inspect_worker!(log::Level::Warn, $arg0);
    );
    ($arg0: expr, $($arg:tt)*) => (
        inspect_worker_error!(log::Level::Warn, $arg0, $($arg)*);
    )
}
