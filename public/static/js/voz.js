// Lançamento por voz: ouve (Web Speech API, pt-BR), envia o texto ao servidor para
// interpretar e mostra o resultado para o usuário conferir antes de salvar pelo /add.
// Sem reconhecimento de voz no navegador (ex.: alguns iPhones com o app na tela inicial),
// o usuário digita ou usa o microfone do próprio teclado no mesmo campo.
(function () {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const $ = id => document.getElementById(id);
    const modal = $('vozModal'), etapaOuvir = $('voz-etapa-ouvir'), form = $('voz-etapa-confirmar');
    const mic = $('voz-mic'), status = $('voz-status'), campoTexto = $('voz-texto');
    const csrf = form.querySelector('[name=csrf_token]').value;

    const DICA = 'Ex.: "gastei R$ 9,90 com barrinha de cereal" ou "ontem recebi 25 reais de uma venda".';
    let rec = null, ouvindo = false, erroVoz = false, categorias = { Receita: [], Despesa: [] };

    function setStatus(msg, erro) {
        status.textContent = msg;
        status.classList.toggle('erro', !!erro);
    }

    // ── Abrir / fechar ───────────────────────────────────────────────────────
    function abrir() {
        mostrarEtapaOuvir();
        campoTexto.value = '';
        modal.style.display = 'flex';
        if (SR) {
            ouvir();                 // o toque no botão é o gesto que libera o microfone
        } else {
            mic.hidden = true;
            setStatus('Este navegador não reconhece voz aqui. Toque no campo abaixo e use o ' +
                      'microfone do teclado (ou digite). ' + DICA);
            campoTexto.focus();
        }
    }

    function fechar() {
        if (rec) { rec.onend = null; rec.abort(); }
        ouvindo = false;
        mic.classList.remove('ouvindo');
        modal.style.display = 'none';
    }

    function mostrarEtapaOuvir() {
        form.hidden = true;
        etapaOuvir.hidden = false;
    }

    // ── Reconhecimento de voz ────────────────────────────────────────────────
    function ouvir() {
        if (ouvindo) { rec.stop(); return; }
        erroVoz = false;
        rec = new SR();
        rec.lang = 'pt-BR';
        rec.interimResults = true;
        rec.continuous = false;
        rec.maxAlternatives = 1;

        rec.onstart = () => {
            ouvindo = true;
            mic.classList.add('ouvindo');
            setStatus('Ouvindo… fale agora. ' + DICA);
        };
        rec.onresult = e => {
            let texto = '';
            for (let i = 0; i < e.results.length; i++) texto += e.results[i][0].transcript;
            campoTexto.value = texto.trim();
        };
        rec.onerror = e => {
            erroVoz = true;
            const msgs = {
                'not-allowed': 'Permissão do microfone negada. Libere o microfone para este site nas ' +
                               'configurações do navegador, ou digite abaixo.',
                'service-not-allowed': 'O reconhecimento de voz não está disponível aqui. Use o microfone ' +
                                       'do teclado no campo abaixo, ou digite.',
                'no-speech': 'Não ouvi nada. Toque no microfone e tente de novo.',
                'audio-capture': 'Nenhum microfone encontrado.',
                'network': 'Sem conexão com o serviço de voz. Verifique a internet ou digite abaixo.',
                'aborted': '',
            };
            const msg = e.error in msgs ? msgs[e.error] : 'Não consegui ouvir (' + e.error + '). Tente de novo.';
            if (msg) setStatus(msg, true);
            if (e.error === 'service-not-allowed') mic.hidden = true;
        };
        rec.onend = () => {
            ouvindo = false;
            mic.classList.remove('ouvindo');
            if (campoTexto.value.trim()) {
                interpretar();
            } else if (!erroVoz) {
                setStatus('Não entendi. Toque no microfone e tente de novo.', true);
            }
        };
        try {
            rec.start();
        } catch (err) {
            setStatus('Não foi possível iniciar o microfone. Digite abaixo.', true);
        }
    }

    // ── Interpretação (servidor) ─────────────────────────────────────────────
    async function interpretar() {
        const texto = campoTexto.value.trim();
        if (!texto) { setStatus('Fale ou digite o lançamento. ' + DICA, true); return; }
        setStatus('Interpretando…');
        try {
            const resp = await fetch('/voz/interpretar', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                body: JSON.stringify({ texto }),
            });
            const dados = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(dados.erro || 'Erro ' + resp.status);
            preencher(dados);
        } catch (err) {
            setStatus('Não consegui interpretar: ' + err.message, true);
        }
    }

    // ── Etapa de confirmação ─────────────────────────────────────────────────
    function preencherCategorias(tipo, selecionada) {
        const sel = $('voz-categoria');
        sel.innerHTML = '';
        sel.options.add(new Option('— Sem categoria —', ''));
        (categorias[tipo] || []).forEach(c => sel.options.add(new Option(c, c, false, c === selecionada)));
    }

    function formatarBRL(v) {
        return Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    function preencher(d) {
        categorias = d.categorias || categorias;
        $('voz-ouvido').textContent = d.texto;
        $('voz-tipo').value = d.tipo;
        preencherCategorias(d.tipo, d.categoria);
        $('voz-data').value = d.data;
        $('voz-descricao').value = d.descricao;
        $('voz-pago').checked = !!d.pago;
        $('voz-valor-display').value = d.valor != null ? formatarBRL(d.valor) : '';
        $('voz-valor').value = d.valor != null ? Number(d.valor).toFixed(2) : '';

        const avisos = $('voz-avisos');
        avisos.innerHTML = '';
        (d.avisos || []).forEach(a => {
            const li = document.createElement('li');
            li.textContent = a;
            avisos.appendChild(li);
        });
        avisos.hidden = !(d.avisos || []).length;

        etapaOuvir.hidden = true;
        form.hidden = false;
        (d.valor == null ? $('voz-valor-display') : form.querySelector('[type=submit]')).focus();
    }

    // Máscara monetária: digitar "990" vira "9,90"
    $('voz-valor-display').addEventListener('input', e => {
        const cents = parseInt(e.target.value.replace(/\D/g, '') || '0', 10);
        e.target.value = formatarBRL(cents / 100);
        $('voz-valor').value = (cents / 100).toFixed(2);
    });

    $('voz-tipo').addEventListener('change', e => preencherCategorias(e.target.value, ''));

    form.addEventListener('submit', e => {
        const display = $('voz-valor-display');
        if (!(parseFloat($('voz-valor').value) > 0)) {
            e.preventDefault();
            display.setCustomValidity('Informe um valor maior que zero.');
            display.reportValidity();
            return;
        }
        display.setCustomValidity('');
    });

    // ── Ligações ─────────────────────────────────────────────────────────────
    $('voz-fab').addEventListener('click', abrir);
    mic.addEventListener('click', ouvir);
    $('voz-continuar').addEventListener('click', () => { if (rec && ouvindo) rec.stop(); else interpretar(); });
    $('voz-de-novo').addEventListener('click', () => {
        mostrarEtapaOuvir();
        campoTexto.value = '';
        if (SR && !mic.hidden) ouvir(); else { setStatus(DICA); campoTexto.focus(); }
    });
    modal.querySelectorAll('[data-voz-fechar]').forEach(b => b.addEventListener('click', fechar));
    modal.addEventListener('click', e => { if (e.target === modal) fechar(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal.style.display === 'flex') fechar(); });
})();
