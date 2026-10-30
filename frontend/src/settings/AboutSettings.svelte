<script lang="ts">
  import { formatReleaseDate, RELEASED_AT, SUITE_NAME, VERSION } from '../lib/product';

  const releaseDate = formatReleaseDate(RELEASED_AT);
</script>

<section class="mx-auto flex min-h-full max-w-3xl flex-col" aria-label={`About ${SUITE_NAME}`}>
  <div class="pt-4 text-center">
    <img class="mx-auto h-[clamp(5rem,18vh,9rem)] w-[clamp(5rem,18vh,9rem)] object-contain" src="/keivotos-logo.png" alt={`${SUITE_NAME} logo`} />
    <h3 class="mt-4 text-xl font-semibold text-gray-100">{SUITE_NAME}</h3>
  </div>
  <div class="mt-6 border-t border-[#292938]" aria-hidden="true"></div>
  <p id="setting-about" class="mt-auto pt-8 text-center text-sm text-gray-400">
    Version {VERSION} ({releaseDate ?? 'Release date unavailable'})
  </p>
</section>
