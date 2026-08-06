/* 共享的 Markdown 渲染（marked + KaTeX + Mermaid），从 note_editor 抽取 */
let __mdRendererInit = false;

function initMarkdownRenderer() {
    if (__mdRendererInit) return;
    __mdRendererInit = true;

    if (window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            theme: 'dark',
            securityLevel: 'loose'
        });
    }
    if (window.marked) {
        marked.setOptions({ breaks: true, gfm: true });
    }
}

function renderMarkdownInto(content, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const mathBlocks = [];
    let protectedContent = content || '';

    protectedContent = protectedContent
        .replace(/\\\((.*?)\\\)/g, function (match, inner) {
            const index = mathBlocks.length;
            mathBlocks.push('$' + inner + '$');
            return `MATHBLOCK${index}ENDBLOCK`;
        })
        .replace(/\\\[(.*?)\\\]/g, function (match, inner) {
            const index = mathBlocks.length;
            mathBlocks.push('$$' + inner + '$$');
            return `MATHBLOCK${index}ENDBLOCK`;
        });

    protectedContent = protectedContent
        .replace(/\$\$(.*?)\$\$/g, function (match, inner) {
            const index = mathBlocks.length;
            mathBlocks.push(match);
            return `MATHBLOCK${index}ENDBLOCK`;
        })
        .replace(/\$(.*?)\$/g, function (match, inner) {
            const index = mathBlocks.length;
            mathBlocks.push(match);
            return `MATHBLOCK${index}ENDBLOCK`;
        });

    let html = window.marked ? marked.parse(protectedContent) : protectedContent;

    mathBlocks.forEach((block, index) => {
        html = html.replace(`MATHBLOCK${index}ENDBLOCK`, block);
    });

    container.innerHTML = html;

    if (window.renderMathInElement) {
        renderMathInElement(container, {
            delimiters: [
                { left: '$$', right: '$$', display: true },
                { left: '$', right: '$', display: false },
                { left: '\\\\[', right: '\\\\]', display: true },
                { left: '\\\\(', right: '\\\\)', display: false }
            ],
            throwOnError: false
        });
    }

    if (window.mermaid) {
        container.querySelectorAll('pre code.language-mermaid').forEach((codeBlock, index) => {
            const mermaidDiv = document.createElement('div');
            mermaidDiv.className = 'mermaid';
            mermaidDiv.id = `mermaid-${containerId}-${index}`;
            mermaidDiv.textContent = codeBlock.textContent;
            codeBlock.parentElement.replaceWith(mermaidDiv);
        });
        mermaid.run({ nodes: container.querySelectorAll('.mermaid') }).catch(err => console.error(err));
    }
}

/* 可复用编辑器：textarea + 预览
   宽屏（>=768px）时编辑与预览并排同时显示、实时刷新；
   窄屏时退化为"编辑/预览"切换。
   用法：<div id="md-editor-{id}" data-editor-id="{id}" data-textarea-name="user_answer"></div> */
function initMarkdownEditor(wrapperId) {
    const wrapper = document.getElementById(wrapperId);
    if (!wrapper) return;

    initMarkdownRenderer();

    const editorId = wrapper.dataset.editorId;
    const textareaName = wrapper.dataset.textareaName || 'user_answer';
    const placeholder = wrapper.dataset.placeholder || '';
    const rows = wrapper.dataset.rows || '8';

    wrapper.innerHTML = `
        <div class="md-toolbar">
            <div class="flex gap-2">
                <button type="button" data-mode="edit" class="md-mode-btn md-mode-active">${window.MD_I18N ? MD_I18N.edit : '编辑'}</button>
                <button type="button" data-mode="preview" class="md-mode-btn">${window.MD_I18N ? MD_I18N.preview : '预览'}</button>
            </div>
        </div>
        <div class="md-editor-body">
            <textarea id="md-textarea-${editorId}" name="${textareaName}" class="md-editor-textarea" rows="${rows}" placeholder="${placeholder}"></textarea>
            <div id="md-preview-${editorId}" class="md-editor-preview markdown-content" style="display:none"></div>
        </div>
    `;

    const textarea = wrapper.querySelector('textarea');
    const preview = wrapper.querySelector('.md-editor-preview');
    const btns = wrapper.querySelectorAll('.md-mode-btn');
    let narrowMode = 'edit';  // 窄屏下当前显示的模式

    function updatePreview() {
        renderMarkdownInto(textarea.value, `md-preview-${editorId}`);
    }

    function applyLayout(wide) {
        if (wide) {
            // 宽屏：编辑与预览并排常显，实时刷新；隐藏模式按钮
            wrapper.classList.add('md-side-by-side');
            textarea.style.display = 'block';
            preview.style.display = 'block';
            btns.forEach(b => b.style.display = 'none');
            updatePreview();
        } else {
            wrapper.classList.remove('md-side-by-side');
            btns.forEach(b => b.style.display = '');
            if (narrowMode === 'preview') {
                textarea.style.display = 'none';
                preview.style.display = 'block';
            } else {
                textarea.style.display = 'block';
                preview.style.display = 'none';
            }
        }
    }

    const mq = window.matchMedia('(min-width: 768px)');
    mq.addEventListener('change', (e) => applyLayout(e.matches));

    textarea.addEventListener('input', () => {
        if (mq.matches) updatePreview();
    });

    btns.forEach(btn => {
        btn.addEventListener('click', () => {
            btns.forEach(b => b.classList.remove('md-mode-active'));
            btn.classList.add('md-mode-active');
            narrowMode = btn.dataset.mode;
            if (narrowMode === 'preview') {
                textarea.style.display = 'none';
                preview.style.display = 'block';
                updatePreview();
            } else {
                textarea.style.display = 'block';
                preview.style.display = 'none';
            }
        });
    });

    applyLayout(mq.matches);
    return textarea;
}
