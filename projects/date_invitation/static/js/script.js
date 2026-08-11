/* =========================================================================
   script.js
   Controla todo el flujo de la aplicación sin recargar la página:
     - Navegación entre pantallas con animaciones.
     - Corazones flotando en el fondo.
     - Botón "No" que esquiva el cursor.
     - Selección de lugar / experiencia / fecha.
     - Envío final vía fetch a /submit + confetti.
   ========================================================================= */

document.addEventListener('DOMContentLoaded', () => {
    /* ------------------------------------------------------------------
     Estado del "asistente" (lo que el usuario va eligiendo)
     ------------------------------------------------------------------ */
    const state = {
        lugar: null,
        experiencia: null,
        fecha: null,
    };

    const TOTAL_STEPS = 5; // usados para la barra de progreso (paso 6 es la pantalla final)

    /* ------------------------------------------------------------------
     Navegación entre pantallas
     ------------------------------------------------------------------ */
    const screens = Array.from(document.querySelectorAll('.screen'));
    const progressFill = document.getElementById('progressFill');

    function goToStep(stepNumber) {
        const current = document.querySelector('.screen.active');
        const next = document.querySelector(
            `.screen[data-step="${stepNumber}"]`,
        );
        if (!next || next === current) return;

        if (current) {
            current.classList.add('leaving');
            current.classList.remove('active');
            setTimeout(() => current.classList.remove('leaving'), 650);
        }

        // pequeño delay para que la transición de salida se sienta orquestada
        requestAnimationFrame(() => {
            next.classList.add('active');
            playCurrentScreenVideos();
        });

        const progressStep = Math.min(stepNumber, TOTAL_STEPS);
        progressFill.style.width = `${(progressStep / TOTAL_STEPS) * 100}%`;
    }

    /* ------------------------------------------------------------------
     Fondo de corazones flotantes
     ------------------------------------------------------------------ */
    const heartsBg = document.getElementById('heartsBg');
    const HEART_COUNT = 8;

    function spawnHeart() {
        const heart = document.createElement('span');
        heart.className = 'floating-heart';
        heart.textContent = '✦';

        const size = 8 + Math.random() * 10;
        const left = Math.random() * 100;
        const duration = 14 + Math.random() * 8;
        const drift = (Math.random() - 0.5) * 70;

        heart.style.left = `${left}vw`;
        heart.style.fontSize = `${size}px`;
        heart.style.animationDuration = `${duration}s`;
        heart.style.setProperty('--drift', `${drift}px`);

        heartsBg.appendChild(heart);

        // limpiar el elemento cuando termine su animación
        setTimeout(() => heart.remove(), duration * 1000);
    }

    // Sembramos un lote inicial escalonado y luego seguimos generando
    for (let i = 0; i < HEART_COUNT; i++) {
        setTimeout(spawnHeart, i * 1200);
    }
    setInterval(spawnHeart, 2400);

    /* ------------------------------------------------------------------
     Reproducción de videos con audio tras la primera interacción
     ------------------------------------------------------------------ */
    const videos = Array.from(document.querySelectorAll('video'));

    function playCurrentScreenVideos() {
        const activeScreen = document.querySelector('.screen.active');
        const activeVideos = activeScreen
            ? activeScreen.querySelectorAll('video')
            : [];

        videos.forEach((video) => {
            const shouldPlay = Array.from(activeVideos).includes(video);

            if (shouldPlay) {
                if (video.paused) {
                    video.play().catch(() => {});
                }
            } else if (!video.paused) {
                video.pause();
            }
        });
    }

    window.addEventListener('pointerdown', playCurrentScreenVideos, {
        once: true,
    });
    window.addEventListener('touchstart', playCurrentScreenVideos, {
        once: true,
    });
    window.addEventListener('keydown', playCurrentScreenVideos, {once: true});

    /* ------------------------------------------------------------------
     Pantalla 1: botón "No" esquivo + botón "Sí"
     ------------------------------------------------------------------ */
    const heroButtons = document.getElementById('heroButtons');
    const btnYes = document.getElementById('btnYes');
    const btnNo = document.getElementById('btnNo');

    function dodgeNoButton() {
        const containerRect = heroButtons.getBoundingClientRect();
        const btnRect = btnNo.getBoundingClientRect();

        // margen de seguridad para que nunca se salga de la ventana
        const margin = 12;
        const maxX = window.innerWidth - btnRect.width - margin;
        const maxY = window.innerHeight - btnRect.height - margin;

        const randomX = Math.max(margin, Math.random() * maxX);
        const randomY = Math.max(margin, Math.random() * maxY);

        btnNo.style.position = 'fixed';
        btnNo.style.left = `${randomX}px`;
        btnNo.style.top = `${randomY}px`;
    }

    btnNo.addEventListener('mouseenter', dodgeNoButton);
    btnNo.addEventListener(
        'touchstart',
        (e) => {
            // en móvil, esquiva también al tocar (sin permitir el click)
            e.preventDefault();
            dodgeNoButton();
        },
        {passive: false},
    );

    // por si acaso, el botón "No" nunca ejecuta ninguna acción
    btnNo.addEventListener('click', (e) => e.preventDefault());

    btnYes.addEventListener('click', () => {
        goToStep(2);
    });

    /* ------------------------------------------------------------------
     Pantalla 2: selección de lugar
     ------------------------------------------------------------------ */
    const lugarCards = document.querySelectorAll('#screen-2 .option-card');

    lugarCards.forEach((card) => {
        card.addEventListener('click', () => {
            lugarCards.forEach((c) => c.classList.remove('selected'));
            card.classList.add('selected');
            state.lugar = card.dataset.value;

            setTimeout(() => goToStep(3), 350);
        });
    });

    /* ------------------------------------------------------------------
     Pantalla 3: selección de experiencia
     ------------------------------------------------------------------ */
    const experienciaCards = document.querySelectorAll('#screen-3 .mini-card');

    experienciaCards.forEach((card) => {
        card.addEventListener('click', () => {
            experienciaCards.forEach((c) => c.classList.remove('selected'));
            card.classList.add('selected');
            state.experiencia = card.dataset.value;

            setTimeout(() => goToStep(4), 350);
        });
    });

    /* ------------------------------------------------------------------
     Pantalla 4: fecha
     ------------------------------------------------------------------ */
    const dateInput = document.getElementById('dateInput');
    const btnDateNext = document.getElementById('btnDateNext');

    // no permitir fechas pasadas
    const today = new Date().toISOString().split('T')[0];
    dateInput.setAttribute('min', today);

    dateInput.addEventListener('change', () => {
        btnDateNext.disabled = !dateInput.value;
    });

    btnDateNext.addEventListener('click', () => {
        if (!dateInput.value) return;
        state.fecha = dateInput.value;
        fillSummary();
        goToStep(5);
    });

    /* ------------------------------------------------------------------
     Pantalla 5: resumen + envío
     ------------------------------------------------------------------ */
    const summaryLugar = document.getElementById('summaryLugar');
    const summaryExperiencia = document.getElementById('summaryExperiencia');
    const summaryFecha = document.getElementById('summaryFecha');
    const btnSubmit = document.getElementById('btnSubmit');
    const statusMessage = document.getElementById('statusMessage');

    function formatFecha(isoDate) {
        if (!isoDate) return '—';
        const [year, month, day] = isoDate.split('-');
        const meses = [
            'enero',
            'febrero',
            'marzo',
            'abril',
            'mayo',
            'junio',
            'julio',
            'agosto',
            'septiembre',
            'octubre',
            'noviembre',
            'diciembre',
        ];
        return `${parseInt(day, 10)} de ${meses[parseInt(month, 10) - 1]} de ${year}`;
    }

    function fillSummary() {
        summaryLugar.textContent = state.lugar || '—';
        summaryExperiencia.textContent = state.experiencia || '—';
        summaryFecha.textContent = formatFecha(state.fecha);
    }

    btnSubmit.addEventListener('click', async () => {
        btnSubmit.disabled = true;
        btnSubmit.textContent = 'Enviando…';
        statusMessage.textContent = '';

        try {
            const response = await fetch('/submit', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    lugar: state.lugar,
                    experiencia: state.experiencia,
                    fecha: state.fecha,
                }),
            });

            const result = await response.json();

            if (response.ok) {
                launchConfetti();
                setTimeout(() => goToStep(6), 600);
            } else {
                statusMessage.textContent =
                    result.message || 'Algo salió mal. Intenta de nuevo.';
                btnSubmit.disabled = false;
                btnSubmit.textContent = 'Enviar respuesta';
            }
        } catch (error) {
            statusMessage.textContent = 'No se pudo conectar con el servidor.';
            btnSubmit.disabled = false;
            btnSubmit.textContent = 'Enviar respuesta';
        }
    });

    /* ------------------------------------------------------------------
     Confetti simple sobre <canvas>
     ------------------------------------------------------------------ */
    const canvas = document.getElementById('confettiCanvas');
    const ctx = canvas.getContext('2d');

    function resizeCanvas() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
    }
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    const CONFETTI_COLORS = [
        '#FF6F91',
        '#E94F77',
        '#F1E7FF',
        '#FFD1DC',
        '#FFFFFF',
    ];

    function launchConfetti() {
        const pieces = Array.from({length: 140}, () => ({
            x: Math.random() * canvas.width,
            y: -20 - Math.random() * canvas.height * 0.5,
            size: 6 + Math.random() * 6,
            color: CONFETTI_COLORS[
                Math.floor(Math.random() * CONFETTI_COLORS.length)
            ],
            speedY: 2 + Math.random() * 3,
            speedX: (Math.random() - 0.5) * 3,
            rotation: Math.random() * 360,
            rotationSpeed: (Math.random() - 0.5) * 8,
        }));

        let frame = 0;
        const maxFrames = 220;

        function animate() {
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            pieces.forEach((p) => {
                p.x += p.speedX;
                p.y += p.speedY;
                p.rotation += p.rotationSpeed;

                ctx.save();
                ctx.translate(p.x, p.y);
                ctx.rotate((p.rotation * Math.PI) / 180);
                ctx.fillStyle = p.color;
                ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6);
                ctx.restore();
            });

            frame++;
            if (frame < maxFrames) {
                requestAnimationFrame(animate);
            } else {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
            }
        }

        requestAnimationFrame(animate);
    }
});
