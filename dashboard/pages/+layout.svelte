<script>
	import '@evidence-dev/tailwind/fonts.css';
	import '../app.css';
	import { dev } from '$app/environment';
	import { EvidenceDefaultLayout } from '@evidence-dev/core-components';
	export let data;
</script>

<!--
  Evidence's template layout (.evidence/template/src/pages/+layout.svelte, 40.1.8)
  plus one addition: Vercel Web Analytics. Vercel serves the script itself at
  /_vercel/insights/script.js on every deployment of the project — no package,
  no key — and it counts page views once Analytics is enabled on the project.
  Skipped in `npm run dev`, where that path does not exist. When upgrading
  Evidence, re-copy the template over this file and re-add the block below.
-->
<svelte:head>
	{#if !dev}
		<script defer src="/_vercel/insights/script.js"></script>
	{/if}
</svelte:head>

<EvidenceDefaultLayout {data}>
	<slot slot="content" />
</EvidenceDefaultLayout>
