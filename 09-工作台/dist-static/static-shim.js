/* 静态快照 shim
 *
 * 这个文件只存在于打包产物（dist-static/）里，不在源码树。它做三件事，
 * 让整套前端在**没有 Python 服务、没有 SQLite、不连 Agent** 的情况下照常跑：
 *
 *   1. 劫持 fetch，把 /api/... 改指打包时固化下来的 JSON 文件
 *   2. 把 Agent 触发、写入类请求挡掉，回一个「静态快照不含此能力」的正常响应
 *      —— 回正常响应而不是让它 404，否则任务面板只会显示「接口返回 404」，
 *         看的人分不清是包坏了还是本来就没有
 *   3. 在页面顶部挂一条横幅说清这个包做不到的三件事
 *
 * 必须在 shell.js 之前加载（index.html 里的顺序），因为 shell 一起来就 fetch。
 */

(() => {
  'use strict';

  const NATIVE = window.fetch.bind(window);

  /* **绝对路径，不能用 './api'。** 这个前端的 URL 是
     /preinvest/pre-detail/B0B3LM36WB 这种深链，相对路径会解析成
     /preinvest/pre-detail/api/... 全部 404。同一个坑在 index.html 的
     script src 上先踩了一次，这里是第二次 —— 包里凡是指向自己资源的路径
     一律从站点根写起。 */
  const ROOT = '/api';

  /* 打包时生成的 id -> 文件名索引。
     不在前端自己算文件名：Python 的 isalnum() 认中文、JS 的 [0-9A-Za-z] 不认，
     两侧各写一份规则必然在某个 id 上分叉，而那种错没有症状。 */
  let INDEX = null;
  const indexReady = NATIVE(`${ROOT}/_index.json`)
    .then((r) => (r.ok ? r.json() : {}))
    .then((j) => { INDEX = j || {}; })
    .catch(() => { INDEX = {}; });

  /* 预生成的导出文件清单（打包时真跑了一遍后端导出）。 */
  let EXPORTS = [];
  NATIVE(`${ROOT}/static-exports.json`)
    .then((r) => (r.ok ? r.json() : []))
    .then((j) => { EXPORTS = Array.isArray(j) ? j : []; })
    .catch(() => { EXPORTS = []; });

  /* 这些路由是「跑一次」或「写一笔」，静态包里没有对应物。
     用前缀匹配而不是穷举名字：各模块的触发路由都是 run- 开头，或者叫
     analyze / decide / loop / *-status，新增模块时不用回来改这里。

     注意别在这段注释里写 run-<星号><斜杠> 那种写法 —— 那两个字符连在一起
     会提前关掉块注释，后面的中文就变成代码，整个 shim 报
     "Invalid or unexpected token" 而完全不加载。踩过一次。 */
  const ACTION = /(^|\/)(run|run-[a-z-]+|analyze|analyze-status|decide|gate-run|loop|loop-[a-z0-9-]+|loop-status|scheme-save|scheme-delete|[a-z-]*-status)$/;
  const EXPORT_ROUTE = /(^|\/)(export|export-[a-z-]+)$/;

  const json = (obj, status = 200) => new Response(
    JSON.stringify(obj),
    { status, headers: { 'Content-Type': 'application/json; charset=utf-8' } },
  );

  /* 把 /api/<mod>/<res>[/<id>] 映射成静态文件路径。query string 一律丢掉 ——
     快照只有默认参数那一份，这一点由横幅向使用者说明。 */
  function resolve(pathname) {
    const parts = pathname.replace(/^\/api\/?/, '').split('/').filter(Boolean);
    if (!parts.length) return null;
    if (parts.length === 1) return { file: `${ROOT}/${parts[0]}.json` };

    const mod = parts[0];
    const route = parts[1];
    const rest = parts.slice(2).map(decodeURIComponent);

    if (!rest.length) return { file: `${ROOT}/${mod}/${route}.json`, mod, route };

    const key = `${mod}/${route}`;
    const map = (INDEX && INDEX[key]) || null;
    const id = rest.join('/');
    if (map && map[id]) return { file: `${ROOT}/${mod}/${route}/${map[id]}`, mod, route, id };
    // 索引里没有这个对象：明确回 null，让调用方走 404 分支而不是拿到别人的数据
    return { missing: true, mod, route, id };
  }

  window.fetch = async function staticFetch(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();

    let u;
    try {
      u = new URL(url, location.href);
    } catch {
      return NATIVE(input, init);
    }
    if (!u.pathname.startsWith('/api/')) return NATIVE(input, init);

    await indexReady;
    const parts = u.pathname.replace(/^\/api\/?/, '').split('/').filter(Boolean);
    const tail = parts.slice(1).join('/');

    // ---- 导出：给预生成的那份文件，没有预生成的就说清楚 ----
    if (EXPORT_ROUTE.test(tail) || EXPORT_ROUTE.test(parts[1] || '')) {
      const mod = parts[0];
      const route = parts[1];
      const arg = parts[2] ? decodeURIComponent(parts[2]) : null;
      const hit = EXPORTS.find((e) => e.module === mod && e.route === route
        && (arg ? String(e.arg) === arg : !e.arg));
      if (hit) {
        const r = await NATIVE(`/${hit.file}`);
        if (r.ok) {
          const blob = await r.blob();
          const name = hit.file.split('/').pop();
          return new Response(blob, {
            status: 200,
            headers: {
              'Content-Type': 'application/vnd.openxmlformats-officedocument'
                + '.spreadsheetml.sheet',
              'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent(name)}`,
            },
          });
        }
      }
      return json({
        message: '这份是静态快照，现场生成导出需要连着服务。'
          + '包里 exports/ 目录下预生成了几份示例文件，可直接打开。',
      }, 501);
    }

    // ---- Agent 触发 / 写入：回一个体面的「不含此能力」响应 ----
    if (ACTION.test(tail) || ACTION.test(parts[1] || '')) {
      return json({
        run: {
          run_id: null,
          object_id: parts[2] ? decodeURIComponent(parts[2]) : null,
          status: '待确认',
          message: '静态快照不含 Agent 能力。要真跑判断，请打开连着服务的那一版。',
        },
        steps: [{
          label: '静态快照',
          detail: '这个包只把当前已有的结论固化下来，Agent 不在包内。',
          status: '待确认',
          duration_ms: 0,
          sources: ['静态快照'],
        }],
        message: '静态快照不含 Agent 能力',
      });
    }

    // ---- 读取：查表取静态文件 ----
    const hit = resolve(u.pathname);
    if (!hit) return json({ message: '静态快照里没有这个接口' }, 404);
    if (hit.missing) {
      return json({
        message: `这个对象（${hit.id}）没有包含在静态快照里`,
      }, 404);
    }
    const res = await NATIVE(hit.file);
    if (!res.ok) {
      return json({ message: `静态快照缺文件：${hit.file}` }, 404);
    }
    // 原样把 JSON 交回去，Content-Type 要对，shell 那边会 res.json()
    const text = await res.text();
    return new Response(text, {
      status: 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
    });
  };

  /* ---- 顶部横幅：说清这个包做不到什么 ------------------------------------
   *
   * 不写这条的话，看的人会把「调参数没反应」「点运行没反应」当成 bug。
   * 契约 §11 禁止防御性表述写进产品界面，但这里是打包产物的元信息 ——
   * 它说的是「这份文件能做什么」，不是业务口径的免责。
   */
  const BANNER_CSS = `
.sn-banner{position:sticky;top:0;z-index:60;display:flex;align-items:baseline;
  gap:10px;flex-wrap:wrap;padding:7px 16px;background:#111113;color:#f4f4f5;
  font:400 13px/1.5 -apple-system,"SF Pro Text","PingFang SC",sans-serif}
.sn-banner b{font-weight:600}
.sn-banner span{color:#a1a1aa}
.sn-banner .sn-x{margin-left:auto;cursor:pointer;color:#a1a1aa;
  border:0;background:none;font:inherit;padding:0 2px}
.sn-banner .sn-x:hover{color:#f4f4f5}
`;

  function banner() {
    if (document.querySelector('.sn-banner')) return;
    const st = document.createElement('style');
    st.textContent = BANNER_CSS;
    document.head.appendChild(st);
    const el = document.createElement('div');
    el.className = 'sn-banner';
    el.innerHTML = '<b>静态快照</b>'
      + '<span>页面与数据是打包那一刻的样子 ·'
      + ' 参数面板改了不会重算 · Agent 不在包内 ·'
      + ' 导出给的是 exports/ 里预生成的那几份</span>'
      + '<button class="sn-x" type="button" title="收起这条">收起</button>';
    el.querySelector('.sn-x').addEventListener('click', () => el.remove());
    document.body.insertBefore(el, document.body.firstChild);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', banner);
  } else {
    banner();
  }
})();
