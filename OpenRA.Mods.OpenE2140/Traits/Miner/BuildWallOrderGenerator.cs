using OpenRA.Mods.Common.Orders;
using OpenRA.Traits;

namespace OpenRA.Mods.OpenE2140.Traits.Miner;

public class BuildWallOrderGenerator : UnitOrderGenerator
{
	private readonly Actor self;

	public BuildWallOrderGenerator(Actor self)
	{
		this.self = self;
	}

	public override IEnumerable<Order> Order(OpenRA.World world, CPos cell, int2 worldPixel, MouseInput mi)
	{
		if (mi.Button == Game.Settings.Game.MouseButtonPreference.Cancel)
		{
			world.CancelInputMode();
			yield break;
		}

		if (mi.Button == Game.Settings.Game.MouseButtonPreference.Action)
		{
			var queued = mi.Modifiers.HasModifier(Modifiers.Shift);
			if (!queued)
			{
				world.CancelInputMode();
			}

			yield return new Order(WallBuilder.BuildWallID, this.self, Target.FromCell(world, cell), queued);
		}
	}

	public override void SelectionChanged(OpenRA.World world, IEnumerable<Actor> selected)
	{
		world.CancelInputMode();
	}

	public override string GetCursor(OpenRA.World world, CPos cell, int2 worldPixel, MouseInput mi)
	{
		var target = TargetForInput(world, cell, worldPixel, mi);

		return target.Type == TargetType.Terrain ? "wallPlace" : "generic-blocked";
	}

	public override bool InputOverridesSelection(OpenRA.World world, int2 xy, MouseInput mi)
	{
		return true;
	}
}
