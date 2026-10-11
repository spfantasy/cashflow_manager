/* 现金流管理系统 前端脚本（无构建步骤，方便 PyInstaller 打包） */

(function () {
  'use strict';

  // ---------------------------------------------------------------------
  // 模态对话框
  // ---------------------------------------------------------------------
  window.closeModal = function () {
    var backdrop = document.getElementById('modal-backdrop');
    if (backdrop) { backdrop.classList.add('hidden'); }
  };

  window.openModal = function (title, html) {
    var backdrop = document.getElementById('modal-backdrop');
    if (!backdrop) { alert(title + '\n\n' + html.replace(/<[^>]+>/g, '')); return; }
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = html;
    backdrop.classList.remove('hidden');
  };

  // ---------------------------------------------------------------------
  // 危险操作二次确认（删除现金流等）
  // ---------------------------------------------------------------------
  document.addEventListener('submit', function (event) {
    var form = event.target;
    var message = form.getAttribute('data-confirm');
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });

  // ---------------------------------------------------------------------
  // 页面2：勾选、全选、按钮状态
  // ---------------------------------------------------------------------
  window.toggleAll = function () {
    var checks = document.querySelectorAll('.row-check');
    var allChecked = Array.prototype.every.call(checks, function (c) { return c.checked; });
    Array.prototype.forEach.call(checks, function (c) { c.checked = !allChecked; });
    updateSelectedCount();
  };

  function updateSelectedCount() {
    var checks = document.querySelectorAll('.row-check');
    if (!checks.length) { return; }
    var selected = Array.prototype.filter.call(checks, function (c) { return c.checked; }).length;
    var label = document.getElementById('selected-count');
    var button = document.getElementById('delete-button');
    if (label) { label.textContent = '已选 ' + selected + ' 行'; }
    if (button) { button.disabled = selected === 0; }
  }

  document.addEventListener('change', function (event) {
    if (event.target.classList && event.target.classList.contains('row-check')) {
      updateSelectedCount();
    }
  });

  // ---------------------------------------------------------------------
  // 页面3：拖入文件
  // ---------------------------------------------------------------------
  function renderFileList(input) {
    var target = document.getElementById(input.id + '-list');
    if (!target) { return; }
    target.innerHTML = '';
    Array.prototype.forEach.call(input.files, function (file) {
      var line = document.createElement('div');
      line.textContent = '📄 ' + file.name;
      target.appendChild(line);
    });
  }

  function bindDropzones() {
    var zones = document.querySelectorAll('.dropzone');
    Array.prototype.forEach.call(zones, function (zone) {
      var input = document.getElementById(zone.getAttribute('data-input'));
      if (!input) { return; }

      zone.addEventListener('click', function (event) {
        if (event.target !== input) { input.click(); }
      });
      input.addEventListener('change', function () { renderFileList(input); });

      ['dragenter', 'dragover'].forEach(function (name) {
        zone.addEventListener(name, function (event) {
          event.preventDefault();
          zone.classList.add('dragover');
        });
      });
      ['dragleave', 'drop'].forEach(function (name) {
        zone.addEventListener(name, function (event) {
          event.preventDefault();
          zone.classList.remove('dragover');
        });
      });
      zone.addEventListener('drop', function (event) {
        var dropped = event.dataTransfer && event.dataTransfer.files;
        if (!dropped || !dropped.length) { return; }
        var transfer = new DataTransfer();
        Array.prototype.forEach.call(input.files, function (file) { transfer.items.add(file); });
        Array.prototype.forEach.call(dropped, function (file) { transfer.items.add(file); });
        input.files = transfer.files;
        renderFileList(input);
      });
    });
  }

  // ---------------------------------------------------------------------
  // 页面3：需要人工处理时弹对话框
  // ---------------------------------------------------------------------
  function showIssuesIfAny() {
    var holder = document.getElementById('issues-data');
    if (!holder || !holder.textContent.trim()) { return; }
    var issues;
    try { issues = JSON.parse(holder.textContent); } catch (e) { return; }
    if (!issues || !issues.length) { return; }

    var items = issues.map(function (issue) {
      var line = '<li><strong>' + escapeHtml(issue.reason) + '</strong>';
      if (issue.reference) { line += '（' + escapeHtml(issue.reference) + '）'; }
      return line + '</li>';
    }).join('');

    openModal(
      '有 ' + issues.length + ' 条记录导入失败，需要人工处理',
      '<p>下面这些记录没有入库，请确认后在「页面5 手工帐」中补录：</p><ul class="issue-list">' + items + '</ul>'
    );
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // ---------------------------------------------------------------------
  // 页面6：编辑用户
  // ---------------------------------------------------------------------
  window.editSeller = function (id, name, regex, share, order) {
    document.getElementById('seller_id').value = id;
    document.getElementById('seller_name').value = name;
    document.getElementById('match_regex').value = regex || '';
    document.getElementById('share_membership').value = share ? '1' : '0';
    document.getElementById('sort_order').value = order;
    document.getElementById('seller_id').scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  window.resetSellerForm = function () {
    document.getElementById('seller-form').reset();
    document.getElementById('seller_id').value = '';
  };

  document.addEventListener('DOMContentLoaded', function () {
    bindDropzones();
    updateSelectedCount();
    showIssuesIfAny();
  });
})();
