using OpenRA.Mods.Common.Traits;
using OpenRA.Mods.OpenE2140.Activites;
using OpenRA.Primitives;
using OpenRA.Traits;

namespace OpenRA.Mods.OpenE2140.Traits.Miner;

public class WallBuilderInfo : ConditionalTraitInfo, Requires<MobileInfo>
{
	[ActorReference]
	[Desc("Wall actor.")]
	[FieldLoader.Require]
	public readonly string Wall = "";

	[Desc("Number of ticks it takes to build a wall.")]
	public readonly int PreBuildDelay = 0;

	[Desc("Color to use for the target line when building walls.")]
	public readonly Color TargetLineColor = Color.Crimson;

	[Desc("Name of the ammo pool the wall builder uses.")]
	public readonly string AmmoPoolName = "primary";

	[Desc("Ammo the wall builder consumes per wall node.")]
	public readonly int AmmoUsage = 1;

	public override object Create(ActorInitializer init)
	{
		return new WallBuilder(init.Self, this);
	}
}

public class WallBuilder : ConditionalTrait<WallBuilderInfo>, IResolveOrder, ITick
{
	public const string BuildWallID = "BuildWall";

	private CPos? newWallLocation;

	public WallBuilder(Actor self, WallBuilderInfo info)
		: base(info)
	{
	}

	void IResolveOrder.ResolveOrder(Actor self, Order order)
	{
		if (order.OrderString != BuildWallID)
			return;

		self.QueueActivity(new BuildWall(self, self.World.Map.CellContaining(order.Target.CenterPosition)));
	}

	public void OnWallBuilt(Actor self, CPos wallLocation)
	{
		this.newWallLocation = wallLocation;
	}

	void ITick.Tick(Actor self)
	{
		if (this.newWallLocation != null && self.Location != this.newWallLocation)
		{
			self.World.AddFrameEndTask(w =>
			{
				if (!self.World.ActorMap.GetActorsAt(this.newWallLocation.Value).All(a => a == self)) return;

				var mine = w.CreateActor(this.Info.Wall, new TypeDictionary
				{
					new LocationInit(this.newWallLocation.Value),
					new OwnerInit(self.Owner)
				});

				this.newWallLocation = null;
			});
		}
	}
}
