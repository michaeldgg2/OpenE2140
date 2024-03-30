using OpenRA.Activities;
using OpenRA.Mods.Common.Activities;
using OpenRA.Mods.Common.Traits;
using OpenRA.Mods.OpenE2140.Traits.Miner;
using OpenRA.Traits;

namespace OpenRA.Mods.OpenE2140.Activites;

public class BuildWall : Activity
{
	private enum BuildState { None, MovingToTarget, Building }

	private readonly CPos targetLocation;
	private readonly WallBuilder wallBuilder;
	private readonly Mobile mobile;
	private readonly AmmoPool[] ammoPools;

	private BuildState state = BuildState.None;

	public BuildWall(Actor self, CPos targetLocation)
	{
		this.targetLocation = targetLocation;
		this.wallBuilder = self.Trait<WallBuilder>();
		this.mobile = self.Trait<Mobile>();
		this.ammoPools = self.TraitsImplementing<AmmoPool>().Where(p => p.Info.Name == this.wallBuilder.Info.AmmoPoolName).ToArray();
	}

	public override bool Tick(Actor self)
	{
		if (this.IsCanceling)
		{
			return true;
		}

		switch (this.state)
		{
			case BuildState.None:
			{
				if (self.Location != this.targetLocation)
				{
					this.QueueChild(this.mobile.MoveTo(this.targetLocation));
				}

				this.state = BuildState.MovingToTarget;
				break;
			}
			case BuildState.MovingToTarget:
			{
				if (self.Location != this.targetLocation)
				{
					this.QueueChild(this.mobile.MoveTo(this.targetLocation));
				}
				else
				{
					if (this.ammoPools != null)
					{
						var pool = this.ammoPools.FirstOrDefault();
						if (pool == null)
							return false;

						if (pool.CurrentAmmoCount < this.wallBuilder.Info.AmmoUsage)
							return false;
					}

					this.state = BuildState.Building;
					this.QueueChild(new Wait(this.wallBuilder.Info.PreBuildDelay));
				}
				break;
			}
			case BuildState.Building:
			{
				if (this.ammoPools != null)
				{
					var pool = this.ammoPools.FirstOrDefault();
					if (pool == null)
						return false;

					if (!pool.TakeAmmo(self, this.wallBuilder.Info.AmmoUsage))
						return false;
				}

				this.wallBuilder.OnWallBuilt(self, this.targetLocation);
				return true;
			}
			default:
				break;
		}
		return false;
	}

	public override IEnumerable<TargetLineNode> TargetLineNodes(Actor self)
	{
		yield return new TargetLineNode(Target.FromCell(self.World, this.targetLocation), this.wallBuilder.Info.TargetLineColor);
	}

	public override IEnumerable<Target> GetTargets(Actor self)
	{
		yield return Target.FromCell(self.World, this.targetLocation);
	}
}
