<script>
  import { power } from '$lib/api'
  import Fa from 'svelte-fa'
  import { faPowerOff, faRotateRight } from '@fortawesome/free-solid-svg-icons'

  const restart = () => power.set('restart')
  const shutdown = () => power.set('shutdown')

</script>
<div class="control">
  <div class="control-title">Power</div>
  <button on:click={shutdown} class="shutdown">
    <Fa icon={faPowerOff} size="0.85x" />
    <span>Shutdown</span>
  </button>
  <button class="restart" on:click={restart}>
    <Fa icon={faRotateRight} size="0.85x" />
    <span>Restart</span>
  </button>
</div>

<style>
  .control {
    display: flex;
    background: #0000001d;
    padding: 0px 30px;
    height: 50px;
    border-radius: 8px;
    font-size: 18px;
    gap: 16px;
    align-items: center;
  }
  .control-title {
    font-size: 16px;
    flex: 1;
  }
  button {
    font-size: 14px;
    background: none;
    border: none;
    color: inherit;
    font-family: inherit;
    cursor: pointer;
  }
  span {
    padding-left: 4px;
  }
  .shutdown {
    color: red;
  }
  .restart {
    color: orange;
  }
</style>
