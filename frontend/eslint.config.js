import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import globals from 'globals'

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // === Error 级别：必须修复的问题 ===
      'react-hooks/rules-of-hooks': 'error',
      // === Off：react-hooks v5 新规则过于严格，不适合现有代码 ===
      'react-hooks/exhaustive-deps': 'off',
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/preserve-manual-memoization': 'off',
      'react-hooks/refs': 'off',
      'react-refresh/only-export-components': 'off',
      // === TS/JS 规则调整 ===
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
      '@typescript-eslint/ban-ts-comment': 'off',
      '@typescript-eslint/no-empty-object-type': 'off',
      '@typescript-eslint/only-throw-error': 'off',
      'no-undef': 'off',
      'no-unreachable': 'error',
      'no-duplicate-imports': 'off', // TS verbatimModuleSyntax 需要 type import 分开
      'no-case-declarations': 'off',
      'no-constant-condition': 'off',
      'no-empty': 'off',
      'prefer-const': 'off',
      'no-var': 'off',
      'no-useless-escape': 'off',
      'no-useless-catch': 'off',
      'require-await': 'off',
      'no-control-regex': 'off',
      'no-async-promise-executor': 'off',
      'no-prototype-builtins': 'off',
    },
  },
)
