document.addEventListener('DOMContentLoaded', () => {
    const allSyncButtons = document.querySelectorAll('.sync-btn');

    allSyncButtons.forEach(button => {
        button.addEventListener('click', handleSyncClick);
    });

    async function handleSyncClick(event) {
        const btn = event.target;
        
        const originalText = btn.textContent;
        
        btn.disabled = true;
        btn.textContent = 'Syncing...';

        const payload = { ...btn.dataset };

        try {
            const response = await fetch('/sync', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const result = await response.json();

            if (response.ok && result.success) {
                btn.textContent = 'Synced!';
                btn.classList.add('success');
                
                const reportItem = btn.closest('.report-item');
                if (reportItem) {
                    reportItem.style.opacity = '0.5';
                    reportItem.querySelectorAll('.sync-btn').forEach(b => {
                        b.disabled = true;
                        b.style.pointerEvents = 'none';
                    });
                }
            } else {
                throw new Error(result.message || 'Unknown error');
            }

        } catch (error) {
            console.error('Sync failed:', error);
            btn.textContent = 'Error!';
            btn.classList.add('error');
            
            setTimeout(() => {
                btn.disabled = false;
                btn.textContent = originalText;
                btn.classList.remove('error');
            }, 3000); 
        }
    }
});

