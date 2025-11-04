document.getElementById('start-audit-btn').addEventListener('click', () => {
    const logs = document.getElementById('logs');
    const summary = document.getElementById('report-summary');
    const progressText = document.getElementById('progress-text');
    const progressBar = document.getElementById('progress-bar');
    const startButton = document.getElementById('start-audit-btn');
    const reportLink = document.getElementById('report-link-container');

    const selectedMediaType = document.querySelector('input[name="mediaType"]:checked').value || 'MANGA';

    logs.textContent = '';
    summary.textContent = 'No report generated yet.';
    progressText.textContent = 'Connecting...';
    progressBar.style.width = '0%';
    progressBar.textContent = '';
    startButton.disabled = true;
    if (reportLink) {
        reportLink.style.display = 'none';
    }


    const evtSource = new EventSource(`/stream-audit?type=${selectedMediaType}`);

    evtSource.addEventListener("log", (event) => {
        const data = JSON.parse(event.data);
        const message = data.message;
        
        logs.textContent += message + '\n';
        logs.scrollTop = logs.scrollHeight;

        if (message.includes("--- Audit Complete ---")) {
            progressText.textContent = "Audit Complete!";
            if (reportLink) {
                reportLink.style.display = 'block';
            }
            evtSource.close(); 
            startButton.disabled = false; 
        }
    });

    evtSource.addEventListener("progress", (event) => {
        const data = JSON.parse(event.data);
        const percent = (data.current / data.total) * 100;
        
        progressBar.style.width = percent + '%';
        if (percent > 20) {
             progressBar.textContent = `${Math.round(percent)}%`;
        }
        progressText.textContent = `(${data.current}/${data.total}) ${data.message}`;
    });

    evtSource.addEventListener("report", (event) => {
        const data = JSON.parse(event.data);
        summary.textContent = JSON.stringify(data, null, 2);
    });

    evtSource.addEventListener("error", (event) => {
        let msg = "Connection error. Stream closed.";
        
        if (event.data) {
             try {
                const data = JSON.parse(event.data);
                msg = data.message;
             } catch(e) {
             }
        }
        
        if (!logs.textContent.includes("--- Audit Complete ---")) {
            logs.textContent += `\n--- ERROR ---\n${msg}\n`;
            progressText.textContent = `Error: ${msg}`;
        }
        
        evtSource.close();
        startButton.disabled = false;
    });
});
