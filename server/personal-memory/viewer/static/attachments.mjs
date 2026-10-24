const failure = (message, status = 0) => Object.assign(new Error(message), {status});
export const attachmentUrl = (recordId, attachmentId) => `./api/files/${encodeURIComponent(recordId)}/${encodeURIComponent(attachmentId)}`;
export const attachmentRepresentsPrimary = record => Boolean(record.href && record.attachments?.some(item => item.href === record.href));

// Each committed file becomes visible immediately; a later failure stops the batch.
export async function uploadAttachments(record, files, csrf, {fetchImpl = (...args) => fetch(...args), onRecord = () => {}} = {}) {
  if (!csrf || !record?.id || !Number.isSafeInteger(record.revision) || record.revision < 1) throw failure('编辑连接不可用，请刷新后再试。');
  const selected = Array.from(files);
  if (selected.some(file => file.size > 50 * 1024 * 1024)) throw failure('每个附件不能超过 50 MiB。', 413);
  let latest = record;
  for (const file of selected) {
    let response;
    try {
      response = await fetchImpl(`./api/attachments?record_id=${encodeURIComponent(latest.id)}&revision=${latest.revision}`, {
        method:'POST', cache:'no-store', headers:{'Content-Type':'application/octet-stream','X-CSRF-Token':csrf,'X-File-Name':encodeURIComponent(file.name)}, body:file
      });
    } catch { throw failure('网络连接中断，无法确认附件是否保存。请刷新记录核对后再试。'); }
    let result;
    try { result = await response.json(); } catch { result = null; }
    if (!response.ok) {
      const messages = {400:'附件名称或内容未通过校验。',403:'编辑授权已失效，请刷新后再试。',408:'附件上传超时，请重试。',409:'记录已被修改或删除。已上传的附件会保留，请刷新后再试。',413:'每个附件不能超过 50 MiB。',503:'附件未能保存，请稍后重试。'};
      throw failure(messages[response.status] || '附件未能保存，请稍后重试。', response.status);
    }
    if (result?.record?.id !== latest.id || !Number.isSafeInteger(result.record.revision) || result.record.revision <= latest.revision || !Array.isArray(result.record.attachments)) {
      throw failure('无法确认附件是否保存，请刷新记录核对后再试。');
    }
    latest = result.record;
    onRecord(latest);
  }
  return latest;
}
