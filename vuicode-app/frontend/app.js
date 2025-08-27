

// const API = location.origin.replace(/\/+$/, '');
const API = 'http://localhost:8080';

const $ = (id) => document.getElementById(id);
const out = (id, txt) => { $(id).textContent = typeof txt === 'string' ? txt : JSON.stringify(txt, null, 2); };

$('btnGen').onclick = async () => {
  const topic = $('topic').value.trim();
  const slugRaw = $('projName').value.trim();
  const backend_template = $('beTpl').value.trim();
  const frontend_template = $('feTpl').value.trim();
  const dry_run = $('dryRun').checked;
  const skip_repair = $('skipRepair').checked;

  // required checks
  if (!topic) return out('genOut', 'Please enter a topic.');
  if (!slugRaw) return out('genOut', 'Please enter a project name (slug).');
  if (!backend_template) return out('genOut', 'Please enter a backend template name.');
  if (!frontend_template) return out('genOut', 'Please enter a frontend template name.');

  out('genOut', 'Submitting job...');

  try {
    const r = await fetch(API + '/api/generate', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        topic,
        slug: slugRaw,
        backend_template,
        frontend_template,
        dry_run,
        skip_repair,
        mode: 'all'
      })
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || 'request failed');

    $('jobId').value = j.job_id;
    $('slug').value = j.slug;
    out('genOut', j);
    $('demoLink').textContent = `/demo/${j.slug}/frontend/`;
  } catch (e) {
    out('genOut', 'Error: ' + e.message);
  }
};

$('btnPoll').onclick = async () => {
  const jobId = $('jobId').value.trim();
  if (!jobId) { out('statusOut', 'Enter a job id.'); return; }
  try {
    const r = await fetch(API + '/api/status/' + jobId);
    const j = await r.json();
    out('statusOut', j);
  } catch (e) {
    out('statusOut', 'Error: ' + e.message);
  }
};

$('btnBlogEN').onclick = () => fetchBlog('en');
$('btnBlogVI').onclick = () => fetchBlog('vi');
$('btnScript').onclick = () => fetchScript();

async function fetchBlog(lang) {
  const slug = $('slug').value.trim();
  if (!slug) { out('previewOut','Enter a slug.'); return; }
  try {
    const r = await fetch(API + `/api/preview/blog?slug=${encodeURIComponent(slug)}&lang=${lang}`);
    const j = await r.json();
    out('previewOut', j.markdown || j);
  } catch (e) {
    out('previewOut', 'Error: ' + e.message);
  }
}

async function fetchScript() {
  const slug = $('slug').value.trim();
  if (!slug) { out('previewOut','Enter a slug.'); return; }
  try {
    const r = await fetch(API + `/api/preview/script?slug=${encodeURIComponent(slug)}`);
    const j = await r.json();
    out('previewOut', j.script || j);
  } catch (e) {
    out('previewOut', 'Error: ' + e.message);
  }
}

$('btnPublish').onclick = async () => {
  const slug = $('slug').value.trim();
  if (!slug) { out('pubOut','Enter a slug.'); return; }
  try {
    const r = await fetch(API + '/api/publish', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ slug })
    });
    const j = await r.json();
    out('pubOut', j);
  } catch (e) {
    out('pubOut', 'Error: ' + e.message);
  }
};