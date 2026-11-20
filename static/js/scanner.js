(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
  const message = document.getElementById("scan-message");

  function getToken(value) {
    const raw = value.trim();
    if (/^[A-Za-z0-9_-]{32,64}$/.test(raw)) return raw;
    try {
      const url = new URL(raw);
      const match = url.pathname.match(/\/attendance\/scan\/([^/]+)/);
      if (match) return decodeURIComponent(match[1]);
    } catch (error) {
      return null;
    }
    return null;
  }

  async function submitToken(value) {
    const token = getToken(value);
    if (!token) {
      message.textContent = "That doesn't look like an EventEase attendance QR code. Try scanning again.";
      message.className = "scan-message scan-message-error";
      return;
    }
    message.textContent = "Checking your registration…";
    message.className = "scan-message";
    const response = await fetch("/attendance/mark", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ token })
    });
    const result = await response.json();
    message.textContent = result.message;
    message.className = `scan-message ${result.ok ? "scan-message-success" : "scan-message-error"}`;
    if (result.ok) {
      const link = document.createElement("a");
      link.href = result.certificate_url;
      link.className = "btn btn-primary-purple mt-3";
      link.textContent = "Download your certificate";
      message.insertAdjacentElement("afterend", link);
    }
  }

  const confirmButton = document.getElementById("confirm-attendance");
  if (confirmButton) {
    confirmButton.addEventListener("click", async () => {
      confirmButton.disabled = true;
      try {
        await submitToken(confirmButton.dataset.token);
        if (message.classList.contains("scan-message-success")) confirmButton.hidden = true;
      } catch (error) {
        message.textContent = "We couldn't reach the server. Check your connection and try again.";
        message.className = "scan-message scan-message-error";
        confirmButton.disabled = false;
      }
    });
  }

  const manualForm = document.getElementById("manual-scan-form");
  if (manualForm) manualForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await submitToken(document.getElementById("manual-token").value);
    } catch (error) {
      message.textContent = "We couldn't reach the server. Check your connection and try again.";
      message.className = "scan-message scan-message-error";
    }
  });

  const startButton = document.getElementById("start-scan");
  const stopButton = document.getElementById("stop-scan");
  if (!startButton || !window.Html5Qrcode) return;
  let scanner;
  startButton.addEventListener("click", async () => {
    startButton.disabled = true;
    message.textContent = "Opening your camera…";
    try {
      scanner = new Html5Qrcode("qr-reader");
      await scanner.start(
        { facingMode: "environment" },
        { fps: 10, qrbox: { width: 240, height: 240 } },
        async (decodedText) => {
          await scanner.stop();
          stopButton.hidden = true;
          startButton.hidden = false;
          startButton.disabled = false;
          await submitToken(decodedText);
        }
      );
      startButton.hidden = true;
      startButton.disabled = false;
      stopButton.hidden = false;
      message.textContent = "Camera is ready. Hold the event QR code in the frame.";
    } catch (error) {
      startButton.disabled = false;
      message.textContent = error?.message || "Camera access was unavailable. Check your browser permissions and try again.";
      message.className = "scan-message scan-message-error";
    }
  });
  stopButton.addEventListener("click", async () => {
    if (scanner?.isScanning) await scanner.stop();
    stopButton.hidden = true;
    startButton.hidden = false;
    message.textContent = "Camera stopped. You can scan again whenever you're ready.";
  });
})();
