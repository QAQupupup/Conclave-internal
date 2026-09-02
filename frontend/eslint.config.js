import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import jsxA11y from 'eslint-plugin-jsx-a11y';

export default tseslint.config(
  { ignores: ['dist'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'jsx-a11y': jsxA11y,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // [P1 修复] 启用 jsx-a11y 无障碍规则，但降级 error→warn 以避免阻塞预存代码。
      // 同时保留 plugin 官方的 off 规则（已废弃的 label-has-for、默认关闭的
      // control-has-associated-label）及各规则选项，避免把其误开为 warn。
      ...Object.fromEntries(
        Object.entries(jsxA11y.configs.recommended.rules).map(([k, v]) => {
          if (v === 'off') return [k, 'off'];
          if (Array.isArray(v) && v[0] === 'off') return [k, v];
          if (Array.isArray(v) && v[0] === 'error') return [k, ['warn', v[1]]];
          return [k, 'warn'];
        })
      ),
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // 窗口分割条（window splitter）是合法的可聚焦 separator 角色：
      // role="separator" + tabIndex + aria-orientation + aria-valuenow + 方向键。
      // jsx-a11y 未将 separator 归为 widget，故在此显式放行该角色，而非关闭规则。
      'jsx-a11y/no-noninteractive-tabindex': ['warn', { roles: ['separator'] }],
      // 列表行（board 会议行）采用可点击行范式：li + role="button" + tabIndex +
      // Enter keydown + aria-label，键盘可达性完整，故按官方文档的白名单机制
      // 显式放行 li→button 组合（保留其余组合的告警），而非关闭规则。
      'jsx-a11y/no-noninteractive-element-to-interactive-role': [
        'warn',
        {
          ul: ['listbox', 'menu', 'menubar', 'radiogroup', 'tablist', 'tree', 'treegrid'],
          ol: ['listbox', 'menu', 'menubar', 'radiogroup', 'tablist', 'tree', 'treegrid'],
          li: ['menuitem', 'option', 'row', 'tab', 'treeitem', 'button'],
          img: ['button'],
        },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-empty-object-type': 'warn',
      'no-empty': ['warn', { allowEmptyCatch: true }],
    },
  }
);
