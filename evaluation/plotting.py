"""
Visualization for a single Simulator run's collected history. Always saves
to file (not plt.show()) -- robust regardless of whether a display is
available, and gives you a file to compare across runs.
"""
import matplotlib.pyplot as plt


def plot_run(p_load_hist, p_grid_hist, soc_hist, title, save_path):
    """
    p_load_hist, p_grid_hist : dict {b_id: [kW per timestep]}
    soc_hist                 : dict {v_id: [SoC per timestep]}
    """
    fig, (ax_load, ax_soc) = plt.subplots(2, 1, figsize=(10, 6))
    fig.suptitle(title)

    for b_id in p_load_hist:
        t = range(len(p_load_hist[b_id]))
        ax_load.plot(t, p_load_hist[b_id], linestyle='--', label=f'Building {b_id} load')
        ax_load.plot(t, p_grid_hist[b_id], label=f'Building {b_id} grid draw')
    ax_load.set_ylabel('kW')
    ax_load.set_xlabel('timestep')
    ax_load.set_title('Building load vs. grid draw')
    ax_load.legend(fontsize=8)

    for v_id, soc in soc_hist.items():
        ax_soc.plot(range(len(soc)), soc, label=f'V{v_id}')
    ax_soc.set_ylabel('SoC')
    ax_soc.set_xlabel('timestep')
    ax_soc.set_title('Vehicle SoC')
    if len(soc_hist) <= 12:
        ax_soc.legend(fontsize=7, ncol=2)

    plt.tight_layout()
    plt.savefig(save_path, dpi=120)
    plt.close(fig)
