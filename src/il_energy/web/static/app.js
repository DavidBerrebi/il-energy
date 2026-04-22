/* EVERGREEN Energy Simulator — Client-side logic */

(function () {
  "use strict";

  // DOM elements
  const form = document.getElementById("upload-form");
  const idfInput = document.getElementById("idf-file");
  const dropZone = document.getElementById("drop-zone");
  const fileLabel = document.getElementById("file-label");
  const epwSelect = document.getElementById("epw-select");
  const zoneSelect = document.getElementById("zone-select");
  const runBtn = document.getElementById("run-btn");

  const inputSection = document.getElementById("input-section");
  const progressSection = document.getElementById("progress-section");
  const statusBadge = document.getElementById("status-badge");
  const logOutput = document.getElementById("log-output");
  const logViewer = document.getElementById("log-viewer");

  const resultsSection = document.getElementById("results-section");
  const gradeBadge = document.getElementById("grade-badge");
  const gradeName = document.getElementById("grade-name");
  const statEpdes = document.getElementById("stat-epdes");
  const statEpref = document.getElementById("stat-epref");
  const statIp = document.getElementById("stat-ip");
  const statArea = document.getElementById("stat-area");
  const unitsTbody = document.getElementById("units-tbody");
  const fileList = document.getElementById("file-list");

  const jobList = document.getElementById("job-list");

  let currentJobId = null;

  // Load EPW files on page load
  loadEpwFiles();
  loadJobHistory();

  // File input change handler
  idfInput.addEventListener("change", function () {
    if (this.files.length > 0) {
      fileLabel.textContent = this.files[0].name;
      dropZone.classList.add("has-file");
    }
  });

  // Drag and drop
  dropZone.addEventListener("dragover", function (e) {
    e.preventDefault();
    this.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", function () {
    this.classList.remove("dragover");
  });
  dropZone.addEventListener("drop", function (e) {
    e.preventDefault();
    this.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      idfInput.files = e.dataTransfer.files;
      fileLabel.textContent = e.dataTransfer.files[0].name;
      dropZone.classList.add("has-file");
    }
  });

  // Form submission
  form.addEventListener("submit", async function (e) {
    e.preventDefault();

    const idfFile = idfInput.files[0];
    if (!idfFile) {
      alert("Please select an IDF file.");
      return;
    }

    const epwPath = epwSelect.value;
    if (!epwPath) {
      alert("Please select a weather file.");
      return;
    }

    // Disable form
    runBtn.disabled = true;
    runBtn.textContent = "Starting...";

    const formData = new FormData();
    formData.append("idf", idfFile);
    formData.append("epw_path", epwPath);
    formData.append("climate_zone", zoneSelect.value);

    try {
      const resp = await fetch("/api/jobs", { method: "POST", body: formData });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Failed to start job");
      }
      const data = await resp.json();
      currentJobId = data.job_id;

      // Show progress
      showProgress();
      streamLogs(currentJobId);
    } catch (err) {
      alert("Error: " + err.message);
      runBtn.disabled = false;
      runBtn.textContent = "Run Simulation";
    }
  });

  function showProgress() {
    progressSection.classList.remove("hidden");
    resultsSection.classList.add("hidden");
    logOutput.textContent = "";
    statusBadge.textContent = "Running";
    statusBadge.className = "badge badge-running";
    // Scroll to progress
    progressSection.scrollIntoView({ behavior: "smooth" });
  }

  function streamLogs(jobId) {
    const evtSource = new EventSource("/api/jobs/" + jobId + "/logs");

    evtSource.onmessage = function (event) {
      logOutput.textContent += event.data + "\n";
      logViewer.scrollTop = logViewer.scrollHeight;
    };

    evtSource.addEventListener("done", function (event) {
      evtSource.close();
      const status = event.data;

      if (status === "complete") {
        statusBadge.textContent = "Complete";
        statusBadge.className = "badge badge-complete";
        loadResults(jobId);
      } else {
        statusBadge.textContent = "Failed";
        statusBadge.className = "badge badge-failed";
      }

      // Re-enable form
      runBtn.disabled = false;
      runBtn.textContent = "Run Simulation";
      loadJobHistory();
    });

    evtSource.onerror = function () {
      evtSource.close();
      // Check final status
      fetch("/api/jobs/" + jobId)
        .then(function (r) { return r.json(); })
        .then(function (job) {
          if (job.status === "complete") {
            statusBadge.textContent = "Complete";
            statusBadge.className = "badge badge-complete";
            loadResults(jobId);
          } else if (job.status === "failed") {
            statusBadge.textContent = "Failed";
            statusBadge.className = "badge badge-failed";
          }
        });
      runBtn.disabled = false;
      runBtn.textContent = "Run Simulation";
      loadJobHistory();
    };
  }

  async function loadResults(jobId) {
    try {
      const resp = await fetch("/api/jobs/" + jobId);
      const job = await resp.json();

      if (!job.summary) return;

      resultsSection.classList.remove("hidden");
      const s = job.summary;

      // Grade badge
      const grade = s.grade || "-";
      gradeBadge.textContent = grade;
      gradeBadge.className = "grade-badge grade-" + grade.charAt(0).toLowerCase();
      gradeName.textContent = s.grade_name || "";

      // Stats
      statEpdes.textContent = s.ep_des_kwh_m2 != null ? s.ep_des_kwh_m2.toFixed(2) : "-";
      statEpref.textContent = s.ep_ref_kwh_m2 != null ? s.ep_ref_kwh_m2.toFixed(2) : "-";
      statIp.textContent = s.ip_percent != null ? (s.ip_percent > 0 ? "+" : "") + s.ip_percent.toFixed(1) : "-";
      statArea.textContent = s.conditioned_area_m2 != null ? s.conditioned_area_m2.toFixed(0) : "-";

      // Per-unit table
      unitsTbody.innerHTML = "";
      if (s.unit_ratings && s.unit_ratings.length > 0) {
        s.unit_ratings.forEach(function (u) {
          var unitGrade = u.grade ? u.grade.grade : "-";
          var row = document.createElement("tr");
          row.innerHTML =
            "<td>" + esc(u.flat_id) + "</td>" +
            "<td>" + u.floor_number + "</td>" +
            "<td>" + esc(u.floor_type) + "</td>" +
            "<td>" + u.area_m2.toFixed(1) + "</td>" +
            "<td>" + u.ep_des_kwh_m2.toFixed(2) + "</td>" +
            "<td>" + u.ep_ref_kwh_m2.toFixed(2) + "</td>" +
            "<td>" + (u.ip_percent > 0 ? "+" : "") + u.ip_percent.toFixed(1) + "</td>" +
            '<td class="grade-cell">' + esc(unitGrade) + "</td>";
          unitsTbody.appendChild(row);
        });
      }

      // Load files
      loadFiles(jobId);

      resultsSection.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      console.error("Failed to load results:", err);
    }
  }

  async function loadFiles(jobId) {
    try {
      const resp = await fetch("/api/jobs/" + jobId + "/results");
      const files = await resp.json();

      fileList.innerHTML = "";
      files.forEach(function (f) {
        var div = document.createElement("div");
        div.className = "file-item";

        var nameSpan = document.createElement("span");
        nameSpan.className = "file-item-name";
        nameSpan.textContent = f.filename;

        var actions = document.createElement("div");
        actions.className = "file-item-actions";

        var fileUrl = "/api/jobs/" + jobId + "/files/" + encodeURIComponent(f.filename);

        if (f.category === "pdf") {
          var viewBtn = document.createElement("a");
          viewBtn.className = "btn btn-sm btn-primary";
          viewBtn.href = fileUrl;
          viewBtn.target = "_blank";
          viewBtn.textContent = "View";
          actions.appendChild(viewBtn);
        }

        var dlBtn = document.createElement("a");
        dlBtn.className = "btn btn-sm btn-outline";
        dlBtn.href = fileUrl;
        dlBtn.download = f.filename.split("/").pop();
        dlBtn.textContent = "Download";
        actions.appendChild(dlBtn);

        div.appendChild(nameSpan);
        div.appendChild(actions);
        fileList.appendChild(div);
      });
    } catch (err) {
      console.error("Failed to load files:", err);
    }
  }

  async function loadEpwFiles() {
    try {
      const resp = await fetch("/api/epw-files");
      const files = await resp.json();

      epwSelect.innerHTML = "";
      if (files.length === 0) {
        var opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No EPW files found";
        epwSelect.appendChild(opt);
        return;
      }

      files.forEach(function (f) {
        var opt = document.createElement("option");
        opt.value = f.path;
        opt.textContent = f.display_name + " (" + f.filename + ")";
        epwSelect.appendChild(opt);
      });
    } catch (err) {
      epwSelect.innerHTML = '<option value="">Failed to load weather files</option>';
    }
  }

  async function loadJobHistory() {
    try {
      const resp = await fetch("/api/jobs");
      const jobs = await resp.json();

      if (jobs.length === 0) {
        jobList.innerHTML = '<p class="text-dim">No jobs yet.</p>';
        return;
      }

      jobList.innerHTML = "";
      jobs.forEach(function (j) {
        var div = document.createElement("div");
        div.className = "job-item";
        div.onclick = function () { viewJob(j.id); };

        var info = document.createElement("div");
        info.className = "job-item-info";
        info.innerHTML =
          '<div class="job-item-name">' + esc(j.idf_filename) + "</div>" +
          '<div class="job-item-meta">' + esc(j.created_at) +
          " &middot; " + esc(j.status) +
          (j.climate_zone ? " &middot; Zone " + esc(j.climate_zone) : "") + "</div>";

        div.appendChild(info);

        if (j.grade) {
          var gradeEl = document.createElement("div");
          gradeEl.className = "job-item-grade";
          gradeEl.textContent = j.grade;
          div.appendChild(gradeEl);
        }

        jobList.appendChild(div);
      });
    } catch (err) {
      console.error("Failed to load jobs:", err);
    }
  }

  async function viewJob(jobId) {
    currentJobId = jobId;

    try {
      const resp = await fetch("/api/jobs/" + jobId);
      const job = await resp.json();

      // Show log
      progressSection.classList.remove("hidden");
      logOutput.textContent = "";

      // Fetch current logs
      var logs = job.log_lines || [];

      if (job.status === "running") {
        statusBadge.textContent = "Running";
        statusBadge.className = "badge badge-running";
        streamLogs(jobId);
      } else if (job.status === "complete") {
        statusBadge.textContent = "Complete";
        statusBadge.className = "badge badge-complete";
        // Load logs from the log lines already captured
        var logResp = await fetch("/api/jobs/" + jobId + "/logs");
        // For completed jobs, SSE will send all lines then done
        var evtSource = new EventSource("/api/jobs/" + jobId + "/logs");
        evtSource.onmessage = function (event) {
          logOutput.textContent += event.data + "\n";
          logViewer.scrollTop = logViewer.scrollHeight;
        };
        evtSource.addEventListener("done", function () {
          evtSource.close();
        });
        evtSource.onerror = function () { evtSource.close(); };
        loadResults(jobId);
      } else if (job.status === "failed") {
        statusBadge.textContent = "Failed";
        statusBadge.className = "badge badge-failed";
      }

      progressSection.scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      console.error("Failed to view job:", err);
    }
  }

  function esc(str) {
    if (str == null) return "";
    var div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
  }
})();
